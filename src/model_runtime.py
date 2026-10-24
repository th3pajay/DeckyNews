import asyncio
import logging
import os
import shutil
import stat
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from src import article_text, hardware
from src.admission import Admission
from src.models import MODEL_CATALOG, binary_kind

DEFAULT_MODEL = "qwen2.5-0.5b"
_BINARY_URL = "https://github.com/Mozilla-Ocho/llamafile/releases/download/0.9.3/llamafile-0.9.3"
_USER_AGENT = (
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/120.0.0.0 Safari/537.36'
)


def download_file(url: str, dest: Path, label: str, logger: logging.Logger) -> None:
    import urllib.request
    import ssl
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp_path = dest.with_suffix('.tmp')
    context = ssl._create_unverified_context()
    req = urllib.request.Request(url, headers={'User-Agent': _USER_AGENT})
    with urllib.request.urlopen(req, context=context) as response:
        total_size = int(response.headers.get('content-length', 0))
        logger.info(f"{label} size: {total_size / 1024 / 1024:.1f} MB")
        with open(temp_path, 'wb') as f:
            shutil.copyfileobj(response, f)
    temp_path.rename(dest)


def _default_runner_factory(**kwargs):
    from src.llama_inference import LlamaCppSubprocess
    return LlamaCppSubprocess(**kwargs)


class ModelRuntime:
    def __init__(
        self,
        runtime_dir: str,
        plugin_dir: str,
        admission: Admission,
        *,
        selected_model: str = DEFAULT_MODEL,
        idle_timeout_seconds: int = 60,
        downloader: Callable[[str, Path, str, logging.Logger], None] = download_file,
        runner_factory: Callable[..., Any] = _default_runner_factory,
        clock: Callable[[], float] = time.time,
        logger: Optional[logging.Logger] = None,
    ):
        self.runtime_dir = Path(runtime_dir)
        self.plugin_dir = Path(plugin_dir)
        self.model_dir = self.runtime_dir / "models"
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.blocked = article_text.BlockedHosts(self.runtime_dir / "blocked_hosts.json")
        self.admission = admission
        self.selected_model = selected_model if selected_model in MODEL_CATALOG else DEFAULT_MODEL
        self._downloader = downloader
        self._runner_factory = runner_factory
        self._clock = clock
        self._log = logger or logging.getLogger("model_runtime")


        def _worker_initializer():
            try:
                if hasattr(os, 'nice'):
                    os.nice(19)
                    self._log.debug("[LLM] Worker thread set to nice 19 (low priority)")
            except Exception as e:
                self._log.debug(f"[LLM] Failed to set nice priority: {e}")

        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="llm",
                                           initializer=_worker_initializer)

        self._llm = None
        self._load_lock = asyncio.Lock()
        self._download_progress: float = 0.0
        self._idle_timeout_seconds = idle_timeout_seconds
        self._last_activity_time: Optional[float] = None
        self._inflight = 0


    def active_config(self) -> Dict:
        return MODEL_CATALOG.get(self.selected_model, MODEL_CATALOG[DEFAULT_MODEL])

    @property
    def model_path(self) -> Path:
        return self.model_dir / self.selected_model / self.active_config()["filename"]

    def set_selected_model(self, model_id: str) -> None:
        if model_id not in MODEL_CATALOG:
            self._log.warning(f"Unknown model ID '{model_id}', ignoring")
            return
        if model_id == self.selected_model:
            return
        self._log.info(f"Switching model: {self.selected_model} -> {model_id}")
        self.unload()
        self._download_progress = 0.0
        self.selected_model = model_id
        self._log.info(f"Selected model is now: {model_id}")


    def binary_candidates(self) -> List[Path]:
        plugin_bin = self.plugin_dir / "bin"
        homebrew_bin = Path.home() / "homebrew" / "plugins" / "DeckyNews" / "bin"
        return [
            self.runtime_dir / "bin" / "llamafile",
            plugin_bin / "llamafile",
            plugin_bin / "llamafile-0.9.3",
            homebrew_bin / "llamafile",
            plugin_bin / "llama-cli",
            plugin_bin / "main",
            homebrew_bin / "llama-cli",
            Path("/usr/local/bin/llama-cli"),
        ]

    def _ensure_executable(self, path: Path) -> bool:
        kind = binary_kind(path)
        if os.access(path, os.X_OK):
            self._log.info(f"Found executable {kind} binary: {path}")
            return True
        self._log.warning(f"Binary found but not executable: {path} (type: {kind})")
        try:
            path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            if os.access(path, os.X_OK):
                self._log.info(f"Fixed permissions for {kind}: {path}")
                return True
        except (OSError, PermissionError) as e:
            self._log.error(f"Failed to fix permissions for {path}: {e}")
        return False

    def find_binary(self) -> Optional[Path]:
        for path in self.binary_candidates():
            if path.exists() and self._ensure_executable(path):
                return path
        return None

    def is_binary_available(self) -> bool:
        return self.find_binary() is not None

    def is_model_downloaded(self) -> bool:
        return self.model_path.exists()


    async def download_model(self) -> bool:
        if self.is_model_downloaded():
            self._log.info("Model already downloaded")
            return True
        if self._load_lock.locked():
            self._log.warning("Model download already in progress")
            return False
        async with self._load_lock:
            target = self.model_path
            self._download_progress = 0.0
            try:
                cfg = self.active_config()
                url = f"https://huggingface.co/{cfg['repo']}/resolve/main/{cfg['filename']}"
                self._log.info(f"Downloading model to: {target}")
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    self.executor, lambda: self._downloader(url, target, "Model", self._log)
                )
                self._download_progress = 100.0
                self._log.info(f"Model downloaded to: {target}")
                return True
            except Exception as e:
                self._log.error(f"Model download failed: {e}")
                self.admission.record_failure()
                target.with_suffix('.tmp').unlink(missing_ok=True)
                return False

    async def download_binary(self) -> bool:
        binary_path = self.runtime_dir / "bin" / "llamafile"
        try:
            self._log.info(f"Downloading llamafile binary from: {_BINARY_URL}")

            def _fetch_and_chmod():
                self._downloader(_BINARY_URL, binary_path, "Binary", self._log)
                binary_path.chmod(stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(self.executor, _fetch_and_chmod)
            self._log.info(f"Binary downloaded to: {binary_path}")
            return True
        except Exception as e:
            self._log.error(f"Binary download failed: {e}")
            binary_path.with_suffix('.tmp').unlink(missing_ok=True)
            return False


    def _migrate_legacy_qwen(self) -> None:
        filename = MODEL_CATALOG[DEFAULT_MODEL]["filename"]
        final = self.model_dir / DEFAULT_MODEL / filename
        for old, label in ((self.model_dir / filename, "flat Qwen model"),
                           (self.model_dir / "llamafile" / filename, "llamafile/ Qwen model")):
            if old.exists() and not final.exists():
                self._log.info(f"Migrating {label} to {DEFAULT_MODEL}/ directory")
                final.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(old), str(final))
                self._log.info("Migration complete")

    async def load_model(self) -> Tuple[bool, Optional[str]]:
        log = self._log
        log.info("load_model: STARTING MODEL LOAD")

        deps = self.check_dependencies()
        missing = [name for name, status in deps.items() if not status["available"]]
        if missing:
            log.error(f"Missing dependencies: {', '.join(missing)}")
            log.error("This indicates a bundling issue. The plugin may need to be reinstalled.")

        if self._llm is not None:
            log.info("Model already loaded, skipping initialization")
            return True, None

        self._migrate_legacy_qwen()

        model_path = self.model_path
        if not model_path.exists():
            log.error("Model not downloaded, cannot load")
            return False, "model_not_downloaded"
        try:
            log.info(f"Model size: {model_path.stat().st_size / (1024 * 1024):.1f} MB")
        except Exception as e:
            log.warning(f"Could not determine model size: {e}")

        binary_path = self.find_binary()
        if not binary_path:
            log.warning("Llamafile binary not found, attempting to download...")
            if not await self.download_binary():
                log.error(f"Llamafile binary download failed; expected at: {self.plugin_dir}/bin/llamafile")
                return False, "binary_not_found"
            binary_path = self.find_binary()
            if not binary_path:
                log.error("Binary still not found after download")
                return False, "binary_download_failed"

        monitor = self.admission.resource_monitor
        can_proceed, reason = monitor.check_resources()
        log.info(f"Resource check: can_proceed={can_proceed}, details={monitor.get_status()}")
        if not can_proceed:
            log.warning(f"Cannot load model due to resource constraints: {reason}")
            return False, f"resource_check_failed: {reason}"

        try:
            log.info(f"Initializing llamafile subprocess wrapper (binary={binary_path}, model={model_path})")
            self._llm = self._runner_factory(
                binary_path=str(binary_path),
                model_path=str(model_path),
                binary_kind=binary_kind(binary_path),
            )
            log.info("load_model: SUCCESS")
            return True, None
        except Exception as e:
            log.error(f"load_model: FAILED - {type(e).__name__}: {e}")
            self.admission.record_failure()
            return False, f"init_exception: {str(e)}"

    def touch(self) -> None:
        self._last_activity_time = self._clock()

    async def extract(self, url: str, timeout_seconds: float, max_chars: int,
                      excerpt: Optional[str] = None) -> article_text.Extraction:
        return await article_text.extract(
            url, executor=self.executor, timeout_seconds=timeout_seconds,
            max_chars=max_chars, logger=self._log, excerpt=excerpt, blocked=self.blocked,
        )

    async def infer(self, prompt: str, *, max_tokens: int, n_threads: int, n_ctx: int,
                    timeout_seconds: float) -> Dict:
        llm = self._llm
        loop = asyncio.get_running_loop()
        self._inflight += 1
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(
                    self.executor,
                    lambda: llm.summarize(prompt, max_tokens=max_tokens, n_threads=n_threads, n_ctx=n_ctx),
                ),
                timeout=timeout_seconds,
            )
        finally:
            self._inflight -= 1

    def unload(self) -> None:
        if self._llm is not None:
            self._llm = None
            self._log.info("LLM model unloaded")

    def delete_model(self) -> bool:
        try:
            self.unload()
            if self.model_path.exists():
                self.model_path.unlink()
                self._log.info(f"Deleted model: {self.model_path}")
            if self.model_dir.exists() and not any(self.model_dir.iterdir()):
                self.model_dir.rmdir()
            return True
        except Exception as e:
            self._log.error(f"Failed to delete model: {e}")
            return False

    async def run_idle_monitor(self) -> None:
        while True:
            await asyncio.sleep(10)
            if self._llm is None or self._last_activity_time is None:
                continue
            idle_time = self._clock() - self._last_activity_time
            if idle_time >= self._idle_timeout_seconds:
                if self._inflight > 0:
                    continue
                self._log.info(f"[LLM] Idle timeout reached ({idle_time:.1f}s), unloading model")
                self.unload()
                self._last_activity_time = None

    def cleanup(self) -> None:
        self.unload()
        self.executor.shutdown(wait=False)


    def status(self) -> Dict:
        cfg = self.active_config()
        return {
            "binary_available": self.is_binary_available(),
            "model_downloaded": self.is_model_downloaded(),
            "model_loaded": self._llm is not None,
            "model_loading": self._load_lock.locked(),
            "download_progress": self._download_progress,
            "selected_model": self.selected_model,
            "model_display_name": cfg["display_name"],
            "model_size_mb": cfg["size_mb"],
            "experimental": cfg.get("experimental", False),
        }

    def check_dependencies(self) -> Dict[str, Dict[str, Any]]:
        def _check_dep(name, getter, log_level="warning"):
            try:
                mod = getter()
                return {"available": True, "version": getattr(mod, "__version__", "unknown"), "error": None}
            except ImportError as e:
                fn = self._log.warning if log_level == "warning" else self._log.error
                fn(f"{name} not available: {e}")
                return {"available": False, "version": None, "error": str(e)}

        deps = {
            "psutil":          _check_dep("psutil", hardware.get_psutil),
            "cloudscraper":    _check_dep("cloudscraper", article_text.get_cloudscraper),
            "readability":     _check_dep("readability", article_text.get_readability, "error"),
            "llama_cpp_python": _check_dep(
                "llama_cpp_python",
                lambda: __import__("src.llama_inference", fromlist=["LlamaCppSubprocess"]),
                "error",
            ),
        }
        available = sum(1 for d in deps.values() if d["available"])
        self._log.info(f"Dependency check: {available}/{len(deps)} available")
        return deps

    def load_diagnostics(self) -> Dict:
        binary_path = self.find_binary()
        candidates = {
            str(p): {"exists": p.exists(), "executable": os.access(str(p), os.X_OK) if p.exists() else False}
            for p in self.binary_candidates()
        }
        model_size = 0
        if self.model_path.exists():
            try:
                model_size = self.model_path.stat().st_size
            except Exception:
                pass
        return {
            "model_path": str(self.model_path),
            "model_exists": self.model_path.exists(),
            "model_size_bytes": model_size,
            "binary_path": str(binary_path) if binary_path else None,
            "binary_exists": binary_path is not None,
            "binary_candidates_checked": candidates,
            "plugin_dir": str(self.plugin_dir),
            "runtime_dir": str(self.runtime_dir),
            "dependencies": self.check_dependencies(),
        }
