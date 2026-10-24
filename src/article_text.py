import asyncio
import json
import logging
import re
import time
from concurrent.futures import Executor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional
from urllib.parse import urlparse

_log = logging.getLogger("article_text")

FETCH_TIMEOUT = 15

_cloudscraper = None
_readability = None


BLOCKED_TTL = 7 * 86400
MIN_TEXT = 100
MIN_EXCERPT = 60


class ExtractionError(Exception):
    def __init__(self, message: str, steps: Optional[List[Dict]] = None):
        super().__init__(message)
        self.steps = steps or []


@dataclass
class Extraction:
    text: str
    method: str
    steps: List[Dict] = field(default_factory=list)


class BlockedHosts:
    def __init__(self, path: Path, clock: Callable[[], float] = time.time):
        self._path = Path(path)
        self._clock = clock
        try:
            self._hosts: Dict[str, float] = json.loads(self._path.read_text())
        except (OSError, ValueError):
            self._hosts = {}

    def contains(self, host: str) -> bool:
        ts = self._hosts.get(host)
        return ts is not None and self._clock() - ts < BLOCKED_TTL

    def add(self, host: str) -> None:
        self._hosts[host] = self._clock()
        try:
            self._path.write_text(json.dumps(self._hosts))
        except OSError:
            pass


def _describe(e: Exception) -> str:
    status = getattr(getattr(e, "response", None), "status_code", None)
    if status:
        return f"the site returned HTTP {status}"
    if isinstance(e, ImportError):
        return f"ImportError: {e}"
    return f"{type(e).__name__}"


def get_cloudscraper():
    global _cloudscraper
    if _cloudscraper is None:
        import cloudscraper
        _cloudscraper = cloudscraper
    return _cloudscraper


def get_readability():
    global _readability
    if _readability is None:
        try:
            from readability import Document
            _readability = Document
        except ImportError as e:
            _log.error(f"readability-lxml import failed: {e}")
            raise ImportError(
                "readability-lxml is not bundled. "
                "This is a plugin packaging bug - please report to the developer."
            ) from e
    return _readability


def prewarm() -> None:
    try:
        get_readability()
        get_cloudscraper()
    except Exception:
        pass


def _fetch_and_clean(url: str, mobile: bool = False) -> Optional[str]:
    profile = {'browser': 'chrome', 'platform': 'android', 'mobile': True} if mobile else \
        {'browser': 'chrome', 'platform': 'linux', 'mobile': False}
    scraper = get_cloudscraper().create_scraper(browser=profile)
    response = scraper.get(url, timeout=FETCH_TIMEOUT - 2)
    response.raise_for_status()

    doc = get_readability()(response.text)
    summary_html = doc.summary()
    if not summary_html:
        return None

    from lxml import html as lxml_html
    text = lxml_html.fromstring(summary_html).text_content()
    return text.strip() if text else None


def _host(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _amp_url(url: str) -> str:
    return url.rstrip("/") + "/amp"


def _clean_excerpt(html: Optional[str]) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def _status(e: Exception) -> Optional[int]:
    return getattr(getattr(e, "response", None), "status_code", None)


async def extract(
    url: str,
    *,
    executor: Optional[Executor],
    timeout_seconds: float,
    max_chars: int,
    logger: Optional[logging.Logger] = None,
    excerpt: Optional[str] = None,
    blocked: Optional[BlockedHosts] = None,
) -> Extraction:
    log = logger or _log
    host = _host(url)
    loop = asyncio.get_running_loop()
    steps: List[Dict] = []
    codes: List[int] = []
    timed_out = False

    async def attempt(name: str, *args) -> Optional[str]:
        nonlocal timed_out
        try:
            text = await asyncio.wait_for(
                loop.run_in_executor(executor, _fetch_and_clean, *args),
                timeout=max(timeout_seconds, FETCH_TIMEOUT),
            )
        except asyncio.TimeoutError:
            timed_out = True
            steps.append({"name": name, "status": "failed", "detail": "timed out"})
            return None
        except Exception as e:
            log.error(f"Article extraction failed ({name}): {e}")
            code = _status(e)
            if code:
                codes.append(code)
            steps.append({"name": name, "status": "failed", "detail": _describe(e)})
            return None
        if text and len(text) > MIN_TEXT:
            steps.append({"name": name, "status": "ok", "detail": ""})
            return text[:max_chars]
        steps.append({"name": name, "status": "failed", "detail": "no readable text"})
        return None

    if blocked and blocked.contains(host):
        steps.append({"name": "Full-text extract", "status": "skipped", "detail": "source remembered as blocked"})
    else:
        text = await attempt("Full-text extract", url)
        if text:
            return Extraction(text, "full", steps)
        if blocked and any(c in (401, 403) for c in codes):
            blocked.add(host)

    if not timed_out:
        for name, target in (("Mobile page", url), ("AMP page", _amp_url(url))):
            text = await attempt(name, target, True)
            if text:
                return Extraction(text, "alt", steps)

    clean = _clean_excerpt(excerpt)
    if len(clean) >= MIN_EXCERPT:
        steps.append({"name": "Feed excerpt", "status": "ok", "detail": ""})
        return Extraction(clean[:max_chars], "excerpt", steps)
    steps.append({"name": "Feed excerpt", "status": "failed", "detail": "feed has no usable excerpt"})

    block_code = next((c for c in codes if c in (401, 403)), None)
    if block_code:
        raise ExtractionError(f"{host} blocks automated readers (HTTP {block_code})", steps)
    if timed_out:
        raise ExtractionError("the site took too long to respond", steps)
    raise ExtractionError("no readable text (paywall or script-rendered page)", steps)
