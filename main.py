import os
import sys


PLUGIN_DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(PLUGIN_DIR, "py_modules"))
sys.path.insert(0, PLUGIN_DIR)

import json
import asyncio
import random
import ssl
import aiohttp
import certifi
import feedparser
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from urllib.parse import urlparse
import decky


from src.database import DatabaseManager
from src.deduplicator import ArticleDeduplicator
from src import article_text
from src.admission import Admission
from src.model_runtime import ModelRuntime
from src.models import LLM_GLOBAL
from src.hardware import SystemHardware
from src.summarizer import Outcome, Summarizer
from src.migrations import drop_json_cache
from src.settings import DEFAULT_SETTINGS, SettingsManager


CONST_DEFAULT_SOURCES = {
    "IGN": "https://feeds.feedburner.com/ign/all",
    "PCGamer": "https://www.pcgamer.com/rss/",
    "Steam": "https://store.steampowered.com/feeds/news.xml",
    "Kotaku": "https://kotaku.com/rss",
    "GameSpot": "https://www.gamespot.com/feeds/news/",
    "Polygon": "https://www.polygon.com/rss/index.xml"
}


NEWS_SOURCES = {}

def get_static_logo_url(source: str) -> str:
    logo_filename = source.lower().replace(' ', '') + '.png'
    return f"/defaults/logos/{logo_filename}"

def get_favicon_url(source_id: str) -> Optional[str]:
    url = NEWS_SOURCES.get(source_id, "")
    domain = urlparse(url).netloc if url else ""
    return f"https://www.google.com/s2/favicons?domain={domain}&sz=32" if domain else None

class SummarizationManager:

    def __init__(self, runtime_dir: str, settings: Dict = DEFAULT_SETTINGS):
        self.ai_personality = settings["aiPersonality"]
        self.admission = Admission(
            SystemHardware(),
            resource_monitoring_enabled=settings["llmResourceMonitoringEnabled"],
            temp_ceiling=settings["llmTempCeilingCelsius"],
            cooldown_seconds=settings["llmCooldownSeconds"],
            thermal_bonus_seconds=settings["llmThermalCooldownBonus"],
            adaptive_tokens=settings["llmAdaptiveTokens"],
            reduced_token_count=settings["llmReducedTokenCount"],
            adaptive_threads=settings["llmAdaptiveThreads"],
            default_threads=LLM_GLOBAL["n_threads"],
            logger=decky.logger,
        )
        self.runtime = ModelRuntime(
            runtime_dir, PLUGIN_DIR, self.admission,
            selected_model=settings["selectedModel"],
            idle_timeout_seconds=settings["llmIdleTimeoutSeconds"],
            logger=decky.logger,
        )
        self.summarizer = Summarizer(
            self.runtime, self.admission, max_prompt_chars=LLM_GLOBAL["max_prompt_chars"], logger=decky.logger
        )

    def set_ai_personality(self, personality: str):
        if personality in ["analyst", "tldr"]:
            self.ai_personality = personality
            decky.logger.info(f"AI personality set to: {personality}")
        else:
            decky.logger.warning(f"Invalid personality '{personality}', keeping current: {self.ai_personality}")

    def apply_setting(self, key: str, value) -> None:
        appliers = {
            "llmCooldownSeconds": lambda v: self.admission.rate_limiter.update_cooldown(v),
            "aiPersonality": lambda v: self.set_ai_personality(v),
            "selectedModel": lambda v: self.runtime.set_selected_model(v),
            "llmTempCeilingCelsius": lambda v: setattr(self.admission.resource_monitor, "max_temp_celsius", v),
            "llmThermalCooldownBonus": lambda v: setattr(self.admission, "thermal_bonus_seconds", v),
            "llmAdaptiveTokens": lambda v: setattr(self.admission, "adaptive_tokens", v),
            "llmReducedTokenCount": lambda v: setattr(self.admission, "reduced_token_count", v),
            "llmAdaptiveThreads": lambda v: setattr(self.admission, "adaptive_threads", v),
        }
        fn = appliers.get(key)
        if fn is not None:
            fn(value)

    def _get_system_prompt(self, personality: str) -> str:
        prompts = {
            "analyst": "Act as a neutral information filter. Extract the core factual event, involved entities, and implications. Remove all promotional language and speculative phrasing. Output 2-3 sentences in a cold, objective tone. Restrict output to claims verifiable within the provided text.",

            "tldr": "Neutral summary. One sentence. Extract the singular core event. No marketing language. No fluff."
        }

        return prompts.get(personality, prompts["analyst"])

    async def summarize_article(self, url: str, title: str = "", allow_during_gaming: bool = False,
                                excerpt: Optional[str] = None) -> Outcome:
        self.runtime.touch()
        status = self.get_status()

        outcome = await self.summarizer.run(
            url,
            cfg=self.runtime.active_config(),
            system_prompt=self._get_system_prompt(self.ai_personality),
            allow_during_gaming=allow_during_gaming,
            excerpt=excerpt,
        )

        if outcome.load_failed:
            outcome.diagnostics = self.runtime.load_diagnostics()
            decky.logger.error(f"LLM load failed: {outcome.error}")
            decky.logger.error(f"Diagnostics: {outcome.diagnostics}")
        elif outcome.success:
            status = self.get_status()
            decky.logger.info(f"Generated summary for: {title or url}")
        outcome.status = status
        return outcome

    def get_status(self) -> Dict:
        return {**self.runtime.status(), **self.admission.status()}

    def cleanup(self):
        self.runtime.cleanup()


@dataclass
class _SourceState:
    health: str = 'ok'
    failures: int = 0
    last_fetch: Optional[datetime] = None
    backoff: float = 0.0


class NewsFetcher:
    def __init__(self, db_manager: DatabaseManager, deduplicator: Optional[ArticleDeduplicator] = None):
        self.db = db_manager
        self.deduplicator = deduplicator
        self._state: Dict[str, _SourceState] = defaultdict(_SourceState)

    @property
    def source_health(self) -> Dict[str, str]:
        return {sid: st.health for sid, st in self._state.items()}

    @staticmethod
    def _in_backoff(st: _SourceState) -> bool:
        if st.backoff <= 0 or st.last_fetch is None:
            return False
        return (datetime.now() - st.last_fetch).total_seconds() < st.backoff

    async def fetch_source(self, source_id: str, session: aiohttp.ClientSession) -> Optional[Dict]:
        if source_id not in NEWS_SOURCES:
            return None

        st = self._state[source_id]
        if self._in_backoff(st):
            decky.logger.info(f"Skipping {source_id} - still in backoff period")
            return None

        url = NEWS_SOURCES[source_id]
        favicon_url = get_favicon_url(source_id)

        try:
            conditional_headers = {}
            stored_etag = self.db.get_metadata(f'etag_{source_id}')
            stored_lastmod = self.db.get_metadata(f'lastmod_{source_id}')
            if stored_etag:
                conditional_headers['If-None-Match'] = stored_etag
            if stored_lastmod:
                conditional_headers['If-Modified-Since'] = stored_lastmod

            _rss_t0 = time.perf_counter()
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15), headers=conditional_headers) as response:
                if response.status == 304:
                    st.health = 'ok'
                    st.failures = 0
                    st.last_fetch = datetime.now()
                    decky.logger.info(f"{source_id}: feed unchanged (304)")
                    return None

                if response.status != 200:
                    raise Exception(f"HTTP {response.status}")

                new_etag = response.headers.get('ETag')
                new_lastmod = response.headers.get('Last-Modified')
                if new_etag:
                    self.db.set_metadata(f'etag_{source_id}', new_etag)
                if new_lastmod:
                    self.db.set_metadata(f'lastmod_{source_id}', new_lastmod)

                max_bytes = 5_242_880
                buf = bytearray()
                while True:
                    chunk = await response.content.read(65536)
                    if not chunk:
                        break
                    buf.extend(chunk)
                    if len(buf) >= max_bytes:
                        decky.logger.warning(f"Feed truncated at 5MB: {source_id}")
                        break
                content = buf.decode(response.charset or 'utf-8', errors='replace')
                _rss_lat = time.perf_counter() - _rss_t0
                decky.logger.debug(f"{source_id}: rss_lat={_rss_lat:.3f}s")
                feed = await asyncio.get_running_loop().run_in_executor(None, feedparser.parse, content)

                if not feed.entries:
                    raise Exception("No entries in feed")

                articles = []
                for entry in feed.entries[:20]:
                    published = entry.get('published_parsed') or entry.get('updated_parsed')
                    if published:
                        pub_datetime = datetime(*published[:6], tzinfo=timezone.utc)
                    else:
                        pub_datetime = datetime.now(timezone.utc)

                    articles.append({
                        'title': entry.get('title', 'No title'),
                        'link': entry.get('link', ''),
                        'published': pub_datetime.isoformat(),
                        'source': source_id,
                        'content': entry.get('summary', ''),
                        'image_url': get_static_logo_url(source_id),
                        'favicon_url': favicon_url,
                    })


                result = await asyncio.get_running_loop().run_in_executor(None, self.db.insert_articles, articles)

                st.health = 'ok'
                st.failures = 0
                st.backoff = 0
                st.last_fetch = datetime.now()

                decky.logger.info(
                    f"Successfully fetched {len(articles)} articles from {source_id} "
                    f"({result['inserted']} new, {result['duplicates']} duplicates)"
                )
                return {'source': source_id, 'articles': articles, 'result': result}

        except Exception as e:
            st.failures += 1
            st.backoff = min(300, 30 * (2 ** st.failures))
            st.last_fetch = datetime.now()
            st.health = 'error' if st.failures >= 3 else 'warning'

            decky.logger.error(f"Failed to fetch {source_id}: {e}")
            return None

    async def fetch_all_sources(self, enabled_sources: List[str]) -> Tuple[int, int]:
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        connector = aiohttp.TCPConnector(ssl=ssl_context, limit=30, limit_per_host=3, ttl_dns_cache=300)

        headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }

        async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
            tasks = [
                self.fetch_source(source_id, session)
                for source_id in enabled_sources
                if source_id in NEWS_SOURCES
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)
            ok = [r for r in results if isinstance(r, dict)]
            inserted = sum(r['result']['inserted'] for r in ok)
            return len(ok), inserted

class Plugin:
    def _load_news_sources(self):
        global NEWS_SOURCES

        sources_file = Path(decky.DECKY_PLUGIN_SETTINGS_DIR) / "sources.json"

        try:
            if sources_file.exists():
                with open(sources_file, 'r', encoding='utf-8') as f:
                    loaded_sources = json.load(f)


                if isinstance(loaded_sources, dict) and all(
                    isinstance(k, str) and isinstance(v, str) and
                    urlparse(v).scheme in ('http', 'https')
                    for k, v in loaded_sources.items()
                ):
                    NEWS_SOURCES = loaded_sources
                    decky.logger.info(f"Loaded {len(NEWS_SOURCES)} sources from sources.json")
                    return
                else:
                    decky.logger.warning("sources.json has invalid format, using defaults")
            else:
                decky.logger.info("sources.json not found, using default sources")
        except Exception as e:
            decky.logger.warning(f"Failed to load sources.json: {e}, using defaults")


        NEWS_SOURCES = CONST_DEFAULT_SOURCES.copy()
        decky.logger.info(f"Using {len(NEWS_SOURCES)} default news sources")

    async def _check_network_connectivity(self) -> bool:
        try:
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get('https://www.google.com', timeout=aiohttp.ClientTimeout(total=5)) as response:
                    return response.status < 500
        except Exception as e:
            decky.logger.debug(f"Network check failed: {e}")
            return False

    def _duplicate_count(self, article_url: str) -> int:
        similarity_hash = self.db_manager.get_similarity_hash_by_url(article_url)
        if not similarity_hash:
            return 0
        return max(0, self.db_manager.count_articles_by_similarity_hash(similarity_hash) - 1)

    async def _main(self):
        self.settings_manager = SettingsManager(decky.DECKY_PLUGIN_SETTINGS_DIR, decky.logger)


        self._load_news_sources()


        drop_json_cache(Path(decky.DECKY_PLUGIN_RUNTIME_DIR), decky.logger)


        self.db_manager = DatabaseManager(decky.DECKY_PLUGIN_RUNTIME_DIR)


        self.settings = self.settings_manager.load()
        self.deduplicator = (
            ArticleDeduplicator(self.settings["deduplicationThreshold"])
            if self.settings["deduplicationEnabled"] else None
        )


        self.news_fetcher = NewsFetcher(self.db_manager, self.deduplicator)

        resource_monitoring = self.settings["llmResourceMonitoringEnabled"]
        self.summarization_manager = SummarizationManager(decky.DECKY_PLUGIN_RUNTIME_DIR, self.settings)


        telemetry_db_path = Path(decky.DECKY_PLUGIN_RUNTIME_DIR) / "telemetry.db"
        from src.telemetry import TelemetryManager, TelemetryProbes
        self.telemetry = TelemetryManager(telemetry_db_path, TelemetryProbes(
            cpu_temperature=self.summarization_manager.admission.hardware.cpu_temperature,
            dup_count=self._duplicate_count,
            dedup_latency=lambda: getattr(self, '_last_dedup_lat', None),
        ))

        self.refresh_task = None
        self.idle_monitor_task = None

        decky.logger.info(f"DeckyNews initialized (with LLM support, resource monitoring: {resource_monitoring})")

        enabled_sources = self.settings['sourcesEnabled']
        decky.logger.info(f"Scheduling initial fetch for sources: {enabled_sources}")

        self.loop = asyncio.get_running_loop()


        self.loop.run_in_executor(None, article_text.prewarm)


        self.idle_monitor_task = self.loop.create_task(
            self.summarization_manager.runtime.run_idle_monitor()
        )

        self.refresh_task = self.loop.create_task(self._initial_fetch_and_refresh_loop())

    def _run_deduplication(self) -> int:
        if not self.deduplicator:
            return 0
        articles = self.db_manager.get_all_articles_for_deduplication(max_articles=500)
        _dedup_t0 = time.perf_counter()
        groups = self.deduplicator.find_duplicates(articles)
        self._last_dedup_lat = time.perf_counter() - _dedup_t0
        if groups:
            self.deduplicator.mark_duplicates_in_db(self.db_manager, groups)
        return len(groups)

    async def _initial_fetch_and_refresh_loop(self):
        for attempt in range(5):
            if await self._check_network_connectivity():
                decky.logger.info(f"Network ready on attempt {attempt + 1}")
                break
            decky.logger.info(f"Network not ready, waiting... (attempt {attempt + 1}/5)")
            await asyncio.sleep(3)
        else:
            decky.logger.warning("Network not ready after 5 attempts, will try fetching anyway")

        try:
            enabled_sources = self.settings['sourcesEnabled']
            decky.logger.info(f"Performing initial fetch for sources: {enabled_sources}")
            ok, inserted = await self.news_fetcher.fetch_all_sources(enabled_sources)
            decky.logger.info(f"Initial fetch completed: {ok}/{len(enabled_sources)} sources, {inserted} new articles")
        except Exception as e:
            decky.logger.error(f"Initial fetch failed: {e}")

        error_backoff = 60
        while True:
            try:
                interval_seconds = self.settings['refreshInterval'] * 60

                await asyncio.sleep(interval_seconds * random.uniform(0.9, 1.1))

                enabled_sources = self.settings['sourcesEnabled']
                _, inserted = await self.news_fetcher.fetch_all_sources(enabled_sources)

                if inserted > 0:
                    self._run_deduplication()
                    if self.settings["autoVacuumEnabled"]:
                        await asyncio.get_running_loop().run_in_executor(None, self.db_manager.vacuum_old_articles)
                    await decky.emit("news_refreshed", {"timestamp": datetime.now().isoformat()})

                error_backoff = 60

            except asyncio.CancelledError:
                break
            except Exception as e:
                decky.logger.error(f"Background refresh error (retry in {error_backoff}s): {e}")
                await asyncio.sleep(error_backoff)
                error_backoff = min(error_backoff * 2, 900)

    async def _unload(self):
        if self.refresh_task:
            self.refresh_task.cancel()
            try:
                await self.refresh_task
            except asyncio.CancelledError:
                pass


        if hasattr(self, 'idle_monitor_task') and self.idle_monitor_task:
            self.idle_monitor_task.cancel()
            try:
                await self.idle_monitor_task
            except asyncio.CancelledError:
                pass


        if hasattr(self, 'summarization_manager'):
            self.summarization_manager.cleanup()


        if hasattr(self, 'db_manager'):
            self.db_manager.close()
            decky.logger.info("Database connection closed")

        decky.logger.info("DeckyNews unloaded")

    async def _uninstall(self):
        import shutil

        if hasattr(self, 'refresh_task') and self.refresh_task:
            self.refresh_task.cancel()
            try:
                await self.refresh_task
            except asyncio.CancelledError:
                pass

        if hasattr(self, 'idle_monitor_task') and self.idle_monitor_task:
            self.idle_monitor_task.cancel()
            try:
                await self.idle_monitor_task
            except asyncio.CancelledError:
                pass

        if hasattr(self, 'summarization_manager'):
            self.summarization_manager.cleanup()

        if hasattr(self, 'db_manager'):
            self.db_manager.close()

        runtime_dir = Path(decky.DECKY_PLUGIN_RUNTIME_DIR)
        if runtime_dir.exists():
            shutil.rmtree(str(runtime_dir), ignore_errors=True)

        settings_dir = Path(decky.DECKY_PLUGIN_SETTINGS_DIR)
        if settings_dir.exists():
            shutil.rmtree(str(settings_dir), ignore_errors=True)

        decky.logger.info("DeckyNews uninstalled")

    async def get_news(self, page: int = 1, items_per_page: int = 10) -> Dict:
        try:
            enabled_sources = self.settings['sourcesEnabled']


            result = self.db_manager.get_articles(
                page=page,
                items_per_page=items_per_page,
                sources=enabled_sources
            )

            decky.logger.info(
                f"get_news: returning {len(result['articles'])} articles "
                f"(page {result['current_page']}/{result['total_pages']}, total: {result['total_articles']})"
            )

            return {
                'articles': result['articles'],
                'total': result['total_articles'],
                'page': result['current_page'],
                'totalPages': result['total_pages']
            }
        except Exception as e:
            decky.logger.error(f"Failed to get news: {e}")
            return {'articles': [], 'total': 0, 'page': 1, 'totalPages': 0}

    async def refresh_news(self) -> bool:
        try:
            enabled_sources = self.settings['sourcesEnabled']
            decky.logger.info(f"Manual refresh triggered for sources: {enabled_sources}")

            ok, inserted = await self.news_fetcher.fetch_all_sources(enabled_sources)
            decky.logger.info(f"Manual refresh completed: {ok}/{len(enabled_sources)} sources, {inserted} new articles")

            if inserted > 0:
                group_count = self._run_deduplication()
                if group_count:
                    decky.logger.info(f"Deduplication: found {group_count} duplicate groups")

                if self.settings["autoVacuumEnabled"]:
                    vacuum_result = await asyncio.get_running_loop().run_in_executor(None, self.db_manager.vacuum_old_articles)
                    if vacuum_result['deleted_count'] > 0 or vacuum_result['vacuumed']:
                        decky.logger.info(
                            f"Database maintenance: deleted {vacuum_result['deleted_count']} old articles, "
                            f"vacuumed: {vacuum_result['vacuumed']}"
                        )


            await decky.emit("news_refreshed", {"timestamp": datetime.now().isoformat()})

            result = ok > 0
            decky.logger.info(f"Refresh result: {result} (returning to frontend)")
            return result
        except Exception as e:
            decky.logger.error(f"Failed to refresh news: {e}")
            return False

    async def mark_article_read(self, link: str, read: bool = True) -> bool:
        try:
            return self.db_manager.mark_read(link, read)
        except Exception as e:
            decky.logger.error(f"Failed to mark article read: {e}")
            return False

    async def delete_article(self, link: str) -> bool:
        try:
            return self.db_manager.delete_by_link(link)
        except Exception as e:
            decky.logger.error(f"Failed to delete article: {e}")
            return False

    async def get_settings(self) -> Dict:
        return self.settings

    async def update_settings(self, new_settings: Dict) -> bool:
        try:
            applied = self.settings_manager.update(new_settings)
            if applied is None:
                return False
            self.settings = self.settings_manager.settings
            for key, value in applied.items():
                self.summarization_manager.apply_setting(key, value)
            return True
        except Exception as e:
            decky.logger.error(f"Failed to update settings: {e}")
            return False

    async def get_sources(self) -> List[str]:
        return list(NEWS_SOURCES)

    async def get_source_health(self) -> Dict:
        return self.news_fetcher.source_health

    async def summarize_article(self, url: str, title: str = "") -> Dict:
        if not self.settings['llmEnabled']:
            return {
                "success": False,
                "error": "LLM summarization is disabled. Enable it in settings.",
                "summary": None,
                "status": None
            }

        session_id = self.telemetry.start_session(url, model_id=self.summarization_manager.runtime.selected_model)

        start_time = time.perf_counter()
        outcome = await self.summarization_manager.summarize_article(
            url, title,
            allow_during_gaming=self.settings["allowLlmDuringGaming"],
            excerpt=self.db_manager.get_excerpt(url),
        )
        total_duration = time.perf_counter() - start_time

        if session_id:
            self.telemetry.record_hardware(session_id)

        if session_id and outcome.success:
            if outcome.fetch_duration:
                self.telemetry.record_timing(session_id, "fetch", outcome.fetch_duration)

            self.telemetry.record_timing(session_id, "inference", total_duration)

            llm_metrics = outcome.llm_metrics or {}

            summary_result = {
                'summary': outcome.summary or '',
                'original_text': outcome.article_text or '',
                'tps': llm_metrics.get('tps'),
                'ttft': llm_metrics.get('ttft'),
                'prompt_eval_time': llm_metrics.get('prompt_eval_time'),
                'total_tokens': llm_metrics.get('total_tokens'),
                'stop_reason': llm_metrics.get('stop_reason'),
                'load_duration': llm_metrics.get('load_duration'),
            }

            self.telemetry.finalize_session(session_id, summary_result, article_url=url)

        return outcome.to_response()

    async def get_llm_status(self) -> Dict:
        return {
            "enabled": self.settings['llmEnabled'],
            **self.summarization_manager.get_status(),
            "diagnostics": self.summarization_manager.runtime.load_diagnostics()
        }

    async def download_llm_model(self) -> Dict:
        try:
            if not self.summarization_manager.runtime.is_binary_available():
                await self.summarization_manager.runtime.download_binary()
            success = await self.summarization_manager.runtime.download_model()
            return {
                "success": success,
                "status": self.summarization_manager.get_status()
            }
        except Exception as e:
            decky.logger.error(f"Model download failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "status": self.summarization_manager.get_status()
            }

    async def unload_llm_model(self) -> bool:
        try:
            self.summarization_manager.runtime.unload()
            return True
        except Exception as e:
            decky.logger.error(f"Failed to unload model: {e}")
            return False

    async def delete_llm_model(self) -> bool:
        try:
            return self.summarization_manager.runtime.delete_model()
        except Exception as e:
            decky.logger.error(f"Failed to delete model: {e}")
            return False

    async def get_coverage_sparkline(self, similarity_hash: str) -> Dict:
        try:
            return self.db_manager.get_coverage_sparkline(similarity_hash)
        except Exception as e:
            decky.logger.error(f"Failed to get coverage sparkline: {e}")
            return {'points': [], 'max_count': 0}

    async def get_telemetry_heatmap(self, hours: int = 6) -> Dict:
        try:
            data = self.telemetry.db.get_heatmap_data(hours)
            return {"success": True, "data": data}
        except Exception as e:
            decky.logger.error(f"Telemetry fetch failed: {e}")
            return {"success": False, "error": str(e)}

    async def export_telemetry_dossier(self) -> Dict:
        try:

            docs_dir = Path.home() / "Documents"
            if not docs_dir.exists():
                docs_dir = Path(decky.DECKY_PLUGIN_RUNTIME_DIR)

            timestamp = int(time.time())
            output_path = docs_dir / f"deckynews_dossier_{timestamp}.txt"

            self.telemetry.export_dossier(output_path)
            return {"success": True, "path": str(output_path)}
        except Exception as e:
            decky.logger.error(f"Telemetry export failed: {e}")
            return {"success": False, "error": str(e)}

    async def clear_telemetry_data(self) -> Dict:
        try:
            self.telemetry.db.clear_all_records()
            return {"success": True}
        except Exception as e:
            decky.logger.error(f"Telemetry clear failed: {e}")
            return {"success": False, "error": str(e)}
