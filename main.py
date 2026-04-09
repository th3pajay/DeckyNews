import os
import sys

# Add py_modules and src to path for bundled dependencies - MUST be before third-party imports
PLUGIN_DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(PLUGIN_DIR, "py_modules"))
sys.path.insert(0, PLUGIN_DIR)  # For src package imports

import json
import asyncio
import ssl
import subprocess
import aiohttp
import certifi
import feedparser
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import urlparse
import decky

# Import LLM subprocess wrapper
from src.llama_inference import LlamaCppSubprocess

# Import database and deduplication modules
from src.database import DatabaseManager
from src.deduplicator import ArticleDeduplicator

# Lazy imports for LLM (only loaded when needed)
_cloudscraper = None
_readability = None
_hf_hub = None

def _get_cloudscraper():
    global _cloudscraper
    if _cloudscraper is None:
        import cloudscraper
        _cloudscraper = cloudscraper
    return _cloudscraper

def _get_readability():
    global _readability
    if _readability is None:
        try:
            from readability import Document
            _readability = Document
        except ImportError as e:
            decky.logger.error(f"readability-lxml import failed: {e}")
            decky.logger.error("This indicates a bundling issue. Please reinstall the plugin.")
            raise ImportError(
                "readability-lxml is not bundled. "
                "This is a plugin packaging bug - please report to the developer."
            ) from e
    return _readability


# Lazy loader for psutil (may not be available on all systems)
_psutil = None

def _get_psutil():
    global _psutil
    if _psutil is None:
        import psutil
        _psutil = psutil
    return _psutil

# Default news sources (fallback if sources.json doesn't exist or fails to load)
CONST_DEFAULT_SOURCES = {
    "IGN": "https://feeds.feedburner.com/ign/all",
    "PCGamer": "https://www.pcgamer.com/rss/",
    "Steam": "https://store.steampowered.com/feeds/news.xml",
    "Kotaku": "https://kotaku.com/rss",
    "GameSpot": "https://www.gamespot.com/feeds/news/",
    "Polygon": "https://www.polygon.com/rss/index.xml"
}

# Runtime news sources (loaded from sources.json or defaults)
NEWS_SOURCES = {}

DEFAULT_SETTINGS = {
    "refreshInterval": 30,
    "debugMode": False,
    "sourcesEnabled": ["IGN", "PCGamer", "Steam", "Kotaku", "GameSpot", "Polygon"],
    "analyticsOptIn": False,
    "llmEnabled": False,
    "llmResourceMonitoringEnabled": True,
    "llmCooldownSeconds": 20,
    # Database & deduplication
    "llmIdleTimeoutSeconds": 60,
    "deduplicationEnabled": True,
    "deduplicationThreshold": 10,
    "autoVacuumEnabled": True,
    # UI appearance
    "uiViewMode": "comfortable",
    "showSourceIcons": True,
    "glassmorphismOpacity": 30,
    "accentColorSource": "automatic",
    "dynamicBackdropEnabled": True,
    "aiTypewriterEnabled": True,
    "aiTypewriterSpeed": 30,
    # Interaction features
    "enableHoverPreview": True,
    "hoverPreviewDelay": 500,
    # AI personality
    "aiPersonality": "analyst",
    # Performance guard
    "performanceGuardEnabled": True,
    "ramThresholdMB": 800,
    "articleRetention": 500,
    "allowLlmDuringGaming": False,
    "llmTempCeilingCelsius": 75,
    "llmThermalCooldownBonus": 30,
    "llmAdaptiveTokens": True,
    "llmReducedTokenCount": 80,
    "llmAdaptiveThreads": True,
    "selectedModel": "qwen2.5-0.5b",
}

def get_static_logo_url(source: str) -> str:
    """Return path to static source logo."""
    logo_filename = source.lower().replace(' ', '') + '.png'
    return f"/defaults/logos/{logo_filename}"

def get_favicon_url(source_id: str) -> Optional[str]:
    url = NEWS_SOURCES.get(source_id, "")
    domain = urlparse(url).netloc if url else ""
    return f"https://www.google.com/s2/favicons?domain={domain}&sz=32" if domain else None

# Global inference settings not specific to any model
LLM_GLOBAL = {
    "n_threads": 2,
    "n_gpu_layers": 0,
    "max_prompt_chars": 2500,
    "temperature": 0.0,
    "repeat_penalty": 1.15,
}

MODEL_CATALOG = {
    "qwen2.5-0.5b": {
        "display_name": "Qwen2.5-0.5B",
        "description": "Default. Instruction-tuned, reliable summaries.",
        "repo": "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
        "filename": "qwen2.5-0.5b-instruct-q4_k_m.gguf",
        "size_mb": 352,
        "prompt_format": "chatml",
        "n_ctx": 1024,
        "max_gen_tokens": 150,
        "timeout_seconds": 15,
    },
    "mobilellm-600m": {
        "display_name": "MobileLLM-600M",
        "description": "Experimental. Mobile-optimized architecture. Lower summary quality.",
        "repo": "RichardErkhov/facebook_-_MobileLLM-600M-gguf",
        "filename": "MobileLLM-600M.Q4_K_M.gguf",
        "size_mb": 430,
        "prompt_format": "completion",
        "n_ctx": 2048,
        "max_gen_tokens": 120,
        "timeout_seconds": 20,
        "experimental": True,
    },
    "llama3.2-1b": {
        "display_name": "Llama 3.2-1B",
        "description": "Meta's 1B instruct model. Better reasoning than Qwen2.5-0.5B.",
        "repo": "bartowski/Llama-3.2-1B-Instruct-GGUF",
        "filename": "Llama-3.2-1B-Instruct-Q4_K_M.gguf",
        "size_mb": 700,
        "prompt_format": "llama3",
        "n_ctx": 2048,
        "max_gen_tokens": 150,
        "timeout_seconds": 20,
    },
    "qwen3-0.6b": {
        "display_name": "Qwen3-0.6B",
        "description": "Newer Qwen generation. Thinking mode disabled.",
        "repo": "bartowski/Qwen_Qwen3-0.6B-GGUF",
        "filename": "Qwen_Qwen3-0.6B-Q4_K_M.gguf",
        "size_mb": 400,
        "prompt_format": "chatml_nothink",
        "n_ctx": 2048,
        "max_gen_tokens": 150,
        "timeout_seconds": 20,
    },
}


SYSTEM_PROMPT = """Act as a neutral information filter. Extract the core factual event, involved entities, and implications. Remove all promotional language and speculative phrasing. Output 2-3 sentences in a cold, objective tone. Restrict output to claims verifiable within the provided text."""


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    """Prevents repeated failures from overwhelming the system."""
    failure_threshold: int = 3
    reset_timeout_seconds: int = 300  # 5 minutes

    failure_count: int = field(default=0, init=False)
    last_failure_time: Optional[datetime] = field(default=None, init=False)
    state: CircuitState = field(default=CircuitState.CLOSED, init=False)

    def can_execute(self) -> bool:
        """Check if request should proceed."""
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            # Check if reset timeout has passed
            if self.last_failure_time:
                elapsed = (datetime.now() - self.last_failure_time).total_seconds()
                if elapsed >= self.reset_timeout_seconds:
                    self.state = CircuitState.HALF_OPEN
                    decky.logger.info("Circuit breaker entering half-open state")
                    return True
            return False

        # HALF_OPEN: allow one test request
        return True

    def record_success(self):
        """Record successful execution."""
        self.failure_count = 0
        self.state = CircuitState.CLOSED
        decky.logger.debug("Circuit breaker: success recorded, state=CLOSED")

    def record_failure(self):
        """Record failed execution."""
        self.failure_count += 1
        self.last_failure_time = datetime.now()

        if self.state == CircuitState.HALF_OPEN:
            # Failed during recovery test
            self.state = CircuitState.OPEN
            decky.logger.warning("Circuit breaker opened after half-open failure")
        elif self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            decky.logger.warning(f"Circuit breaker opened after {self.failure_count} failures")

    def get_status(self) -> Dict:
        """Get current circuit breaker status."""
        return {
            "state": self.state.value,
            "failure_count": self.failure_count,
            "last_failure": self.last_failure_time.isoformat() if self.last_failure_time else None
        }


@dataclass
class ResourceMonitor:
    """Monitors system resources to prevent OOM and thermal issues."""
    min_memory_mb: int = 800       # Minimum free memory required
    max_temp_celsius: int = 80     # Maximum CPU temperature

    def __init__(self, enabled: bool = True, max_temp_celsius: int = 80):
        self.enabled = enabled
        self.max_temp_celsius = max_temp_celsius
        if not enabled:
            decky.logger.warning("ResourceMonitor: Resource monitoring DISABLED - checks will always pass")

    def check_resources(self) -> Tuple[bool, str]:
        """
        Check if system has sufficient resources for LLM inference.
        Returns: (can_proceed, reason)
        """
        if not self.enabled:
            return True, "Resource monitoring disabled"

        try:
            psutil = _get_psutil()
            mem = psutil.virtual_memory()
            available_mb = mem.available / (1024 * 1024)

            if available_mb < self.min_memory_mb:
                return False, f"Insufficient memory: {available_mb:.0f}MB available, {self.min_memory_mb}MB required"
        except Exception as e:
            decky.logger.warning(f"Memory check failed: {e}")
            return True, "Memory check unavailable, allowing operation"

        # Check CPU temperature (Linux/Steam Deck specific)
        try:
            temp = self._get_cpu_temperature()
            if temp and temp > self.max_temp_celsius:
                return False, f"CPU too hot: {temp}°C (max {self.max_temp_celsius}°C)"
        except Exception as e:
            decky.logger.debug(f"Temperature check failed: {e}")
            # Temperature check failure is non-fatal

        return True, "Resources OK"

    def _get_cpu_temperature(self) -> Optional[float]:
        """Get CPU temperature on Linux/Steam Deck."""
        hwmon_paths = [
            "/sys/class/hwmon/hwmon0/temp1_input",
            "/sys/class/hwmon/hwmon1/temp1_input",
            "/sys/class/thermal/thermal_zone0/temp",
        ]

        for path in hwmon_paths:
            try:
                with open(path, 'r') as f:
                    temp = int(f.read().strip()) / 1000
                    return temp
            except (FileNotFoundError, ValueError, PermissionError):
                continue

        try:
            psutil = _get_psutil()
            temps = psutil.sensors_temperatures()
            if temps:
                for name, entries in temps.items():
                    for entry in entries:
                        if entry.current:
                            return entry.current
        except Exception:
            pass

        return None

    async def get_adaptive_thread_count(self) -> int:
        """
        Dynamically adjust thread count based on game running state.
        - Game running: n_threads=1 (minimal impact)
        - Game not running: n_threads=2 (faster inference)
        """
        if await is_game_running():
            return 1
        return 2

    async def should_throttle_llm(self) -> tuple[bool, str]:
        """
        Enhanced resource checks with stricter thresholds during gaming.
        Returns: (should_throttle, reason)
        """
        if not self.enabled:
            return False, "Resource monitoring disabled"

        game_running = await is_game_running()

        if game_running:
            try:
                temp = self._get_cpu_temperature()
                if temp and temp > self.max_temp_celsius - 5:
                    return True, f"CPU too hot during gaming: {temp}°C"
            except Exception:
                pass

            try:
                psutil = _get_psutil()
                mem = psutil.virtual_memory()
                available_mb = mem.available / (1024 * 1024)

                if available_mb < 500:
                    return True, f"Low memory during gaming: {available_mb:.0f}MB"
            except Exception:
                pass

        can_proceed, reason = self.check_resources()
        return not can_proceed, reason

    def get_status(self) -> Dict:
        """Get current resource status."""
        if not self.enabled:
            return {
                "enabled": False,
                "memory_available_mb": None,
                "memory_percent_used": None,
                "cpu_temp_celsius": None,
                "can_proceed": True,
                "message": "Resource monitoring disabled"
            }

        try:
            psutil = _get_psutil()
            mem = psutil.virtual_memory()
            temp = self._get_cpu_temperature()

            return {
                "enabled": True,
                "memory_available_mb": mem.available / (1024 * 1024),
                "memory_percent_used": mem.percent,
                "cpu_temp_celsius": temp,
                "can_proceed": self.check_resources()[0]
            }
        except Exception as e:
            decky.logger.warning(f"Resource status check failed: {e}")
            return {
                "enabled": True,
                "memory_available_mb": None,
                "memory_percent_used": None,
                "cpu_temp_celsius": None,
                "can_proceed": True,  # Allow operation if we can't check
                "error": str(e)
            }


@dataclass
class RateLimiter:
    """Limits summarization requests to prevent thermal issues and battery drain."""
    cooldown_seconds: int = 20       # Cooldown between requests

    last_request_time: Optional[datetime] = field(default=None, init=False)

    def can_request(self) -> Tuple[bool, str]:
        """
        Check if a new request is allowed.
        Returns: (can_proceed, reason)
        """
        now = datetime.now()

        # Check cooldown
        if self.last_request_time:
            elapsed = (now - self.last_request_time).total_seconds()
            if elapsed < self.cooldown_seconds:
                remaining = self.cooldown_seconds - elapsed
                return False, f"Cooldown active: {remaining:.0f}s remaining"

        return True, "OK"

    def record_request(self):
        """Record a summarization request."""
        self.last_request_time = datetime.now()
        decky.logger.info("Rate limiter: request recorded")

    def update_cooldown(self, cooldown_seconds: int):
        """Update the cooldown period."""
        self.cooldown_seconds = cooldown_seconds
        decky.logger.info(f"Rate limiter: cooldown updated to {cooldown_seconds}s")

    def get_status(self) -> Dict:
        """Get current rate limiter status."""
        can_request, reason = self.can_request()
        cooldown_remaining = 0

        if self.last_request_time:
            elapsed = (datetime.now() - self.last_request_time).total_seconds()
            cooldown_remaining = max(0, self.cooldown_seconds - elapsed)

        return {
            "cooldown_remaining_seconds": cooldown_remaining,
            "can_request": can_request,
            "reason": reason
        }


async def is_game_running() -> bool:
    """
    Detect if a game is currently running on Steam Deck.
    Uses pgrep to find Steam game processes.
    """
    try:
        # Steam uses 'reaper SteamLaunch' for running games
        result = await asyncio.create_subprocess_exec(
            'pgrep', '-f', 'reaper SteamLaunch',
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        await result.wait()
        return result.returncode == 0
    except Exception as e:
        decky.logger.debug(f"Game detection failed: {e}")
        # On Windows or other platforms, assume no game running
        return False


class SummarizationManager:
    """
    Manages LLM-based article summarization with safety mechanisms.
    Uses llama-cpp-python for inference, with resource checks and rate limiting.
    """

    def __init__(self, runtime_dir: str, resource_monitoring_enabled: bool = True, cooldown_seconds: int = 20, idle_timeout_seconds: int = 60, ai_personality: str = "analyst", temp_ceiling: int = 75, thermal_cooldown_bonus: int = 30, adaptive_tokens: bool = True, reduced_token_count: int = 80, adaptive_threads: bool = True, selected_model: str = "qwen2.5-0.5b"):
        self.runtime_dir = Path(runtime_dir)
        self.model_dir = self.runtime_dir / "models"
        self.model_dir.mkdir(parents=True, exist_ok=True)

        # AI personality setting
        self.ai_personality = ai_personality

        # Selected model
        self.selected_model = selected_model if selected_model in MODEL_CATALOG else "qwen2.5-0.5b"

        # Thermal guardrail settings
        self._thermal_bonus_seconds = thermal_cooldown_bonus
        self._thermal_bonus_until: Optional[float] = None
        self._adaptive_tokens_enabled = adaptive_tokens
        self._reduced_token_count = reduced_token_count
        self._adaptive_threads_enabled = adaptive_threads

        # Safety mechanisms
        self.circuit_breaker = CircuitBreaker()
        self.resource_monitor = ResourceMonitor(enabled=resource_monitoring_enabled, max_temp_celsius=temp_ceiling)
        self.rate_limiter = RateLimiter(cooldown_seconds=cooldown_seconds)

        # Thread pool for blocking operations with low priority
        def _worker_initializer():
            """Set thread priority to low (nice 19) on Linux"""
            try:
                if hasattr(os, 'nice'):
                    os.nice(19)  # Lowest CPU priority
                    decky.logger.debug("[LLM] Worker thread set to nice 19 (low priority)")
            except Exception as e:
                decky.logger.debug(f"[LLM] Failed to set nice priority: {e}")

        self.executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="llm",
            initializer=_worker_initializer
        )

        # LLM instance (lazy loaded)
        self._llm = None
        self._model_path: Optional[Path] = None
        self._model_load_lock = asyncio.Lock()
        self._download_progress: float = 0.0

        # Idle timeout management
        self._idle_timeout_seconds = idle_timeout_seconds
        self._last_activity_time: Optional[float] = None
        self._idle_timeout_task: Optional[asyncio.Task] = None

    def set_resource_monitoring_enabled(self, enabled: bool):
        """Update resource monitoring enabled state."""
        self.resource_monitor.enabled = enabled
        decky.logger.info(f"Resource monitoring {'enabled' if enabled else 'disabled'}")

    def set_ai_personality(self, personality: str):
        if personality in ["analyst", "tldr"]:
            self.ai_personality = personality
            decky.logger.info(f"AI personality set to: {personality}")
        else:
            decky.logger.warning(f"Invalid personality '{personality}', keeping current: {self.ai_personality}")

    def _get_active_config(self) -> Dict:
        """Return the catalog entry for the currently selected model."""
        return MODEL_CATALOG.get(self.selected_model, MODEL_CATALOG["qwen2.5-0.5b"])

    def set_selected_model(self, model_id: str):
        """Switch to a different model, unloading the current one first."""
        if model_id not in MODEL_CATALOG:
            decky.logger.warning(f"Unknown model ID '{model_id}', ignoring")
            return
        if model_id == self.selected_model:
            return
        decky.logger.info(f"Switching model: {self.selected_model} -> {model_id}")
        self.unload_model()
        self._download_progress = 0.0
        self.selected_model = model_id
        decky.logger.info(f"Selected model is now: {model_id}")

    def check_dependencies(self) -> Dict[str, Dict[str, any]]:
        """
        Check status of all LLM dependencies for diagnostics.
        Returns dict with import status, version info, and error messages.
        """
        deps_status = {}

        # Check psutil (resource monitoring)
        try:
            psutil = _get_psutil()
            deps_status["psutil"] = {
                "available": True,
                "version": getattr(psutil, "__version__", "unknown"),
                "error": None
            }
        except ImportError as e:
            deps_status["psutil"] = {
                "available": False,
                "version": None,
                "error": str(e)
            }
            decky.logger.warning(f"psutil not available: {e}")

        # Check cloudscraper (article fetching)
        try:
            cloudscraper = _get_cloudscraper()
            deps_status["cloudscraper"] = {
                "available": True,
                "version": getattr(cloudscraper, "__version__", "unknown"),
                "error": None
            }
        except ImportError as e:
            deps_status["cloudscraper"] = {
                "available": False,
                "version": None,
                "error": str(e)
            }
            decky.logger.warning(f"cloudscraper not available: {e}")

        # Check readability-lxml (article extraction)
        try:
            readability = _get_readability()
            deps_status["readability"] = {
                "available": True,
                "version": "unknown",
                "error": None
            }
        except ImportError as e:
            deps_status["readability"] = {
                "available": False,
                "version": None,
                "error": str(e)
            }
            decky.logger.error(f"readability-lxml not available: {e}")


        # Check llama-cpp-python (not imported lazily, check separately)
        try:
            from src.llama_inference import LlamaCppSubprocess
            deps_status["llama_cpp_python"] = {
                "available": True,
                "version": "unknown",
                "error": None
            }
        except ImportError as e:
            deps_status["llama_cpp_python"] = {
                "available": False,
                "version": None,
                "error": str(e)
            }
            decky.logger.error(f"llama_cpp_python not available: {e}")

        # Log summary
        available_count = sum(1 for dep in deps_status.values() if dep["available"])
        total_count = len(deps_status)
        decky.logger.info(f"Dependency check: {available_count}/{total_count} available")

        if available_count < total_count:
            missing = [name for name, status in deps_status.items() if not status["available"]]
            decky.logger.warning(f"Missing dependencies: {', '.join(missing)}")

        return deps_status

    def _get_system_prompt(self, personality: str) -> str:
        prompts = {
            "analyst": "Act as a neutral information filter. Extract the core factual event, involved entities, and implications. Remove all promotional language and speculative phrasing. Output 2-3 sentences in a cold, objective tone. Restrict output to claims verifiable within the provided text.",

            "tldr": "Neutral summary. One sentence. Extract the singular core event. No marketing language. No fluff."
        }

        return prompts.get(personality, prompts["analyst"])

    @property
    def model_path(self) -> Path:
        """Get expected model path for the currently selected model."""
        cfg = self._get_active_config()
        return self.model_dir / self.selected_model / cfg["filename"]

    def _get_binary_path(self) -> Optional[Path]:
        """Find llamafile binary and ensure it's executable."""
        plugin_dir = Path(PLUGIN_DIR)
        runtime_bin_dir = self.runtime_dir / "bin"

        candidates = [
            runtime_bin_dir / "llamafile",
            plugin_dir / "bin" / "llamafile",
            plugin_dir / "bin" / "llamafile-0.9.3",
            Path.home() / "homebrew" / "plugins" / "DeckyNews" / "bin" / "llamafile",
            plugin_dir / "bin" / "llama-cli",
            plugin_dir / "bin" / "main",
            Path.home() / "homebrew" / "plugins" / "DeckyNews" / "bin" / "llama-cli",
        ]

        for path in candidates:
            if not path.exists():
                continue

            is_executable = os.access(path, os.X_OK)
            binary_type = "llamafile" if "llamafile" in path.name else "llama-cli"

            if not is_executable:
                decky.logger.warning(f"Binary found but not executable: {path} (type: {binary_type})")
                try:
                    import stat
                    current_mode = path.stat().st_mode
                    path.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

                    if os.access(path, os.X_OK):
                        decky.logger.info(f"Fixed permissions for {binary_type}: {path}")
                        return path
                except (OSError, PermissionError) as e:
                    decky.logger.error(f"Failed to fix permissions for {path}: {e}")
                    continue
            else:
                decky.logger.info(f"Found executable {binary_type} binary: {path}")
                return path

        return None

    def is_binary_available(self) -> bool:
        """Check if the llama-cli binary is available."""
        return self._get_binary_path() is not None

    def is_model_downloaded(self) -> bool:
        """Check if model file exists."""
        return self.model_path.exists()

    async def download_model(self) -> bool:
        """Download the LLM model from HuggingFace Hub. Returns True if successful."""
        if self.is_model_downloaded():
            decky.logger.info("Model already downloaded")
            return True

        if self._model_load_lock.locked():
            decky.logger.warning("Model download already in progress")
            return False

        async with self._model_load_lock:
            # Capture model path NOW to prevent race condition
            target_model_path = self.model_path

            self._download_progress = 0.0

            try:
                decky.logger.info(f"Downloading model to: {target_model_path}")

                def _download():
                    import urllib.request
                    import ssl
                    import shutil

                    cfg = self._get_active_config()
                    model_url = f"https://huggingface.co/{cfg['repo']}/resolve/main/{cfg['filename']}"

                    target_model_path.parent.mkdir(parents=True, exist_ok=True)
                    temp_path = target_model_path.with_suffix('.tmp')

                    context = ssl._create_unverified_context()

                    # Add browser-like User-Agent to bypass HuggingFace CDN blocks
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                    }
                    req = urllib.request.Request(model_url, headers=headers)

                    with urllib.request.urlopen(req, context=context) as response:
                        total_size = int(response.headers.get('content-length', 0))
                        decky.logger.info(f"Model size: {total_size / 1024 / 1024:.1f} MB")

                        with open(temp_path, 'wb') as f:
                            shutil.copyfileobj(response, f)

                    temp_path.rename(target_model_path)
                    return str(target_model_path)

                # Run download in executor
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(self.executor, _download)

                self._download_progress = 100.0
                decky.logger.info(f"Model downloaded to: {target_model_path}")
                return True

            except Exception as e:
                decky.logger.error(f"Model download failed: {e}")
                self.circuit_breaker.record_failure()
                if target_model_path.with_suffix('.tmp').exists():
                    target_model_path.with_suffix('.tmp').unlink()
                return False

    async def download_binary(self) -> bool:
        """Download llamafile binary from GitHub releases."""
        binary_url = "https://github.com/Mozilla-Ocho/llamafile/releases/download/0.9.3/llamafile-0.9.3"
        binary_name = "llamafile"
        binary_path = self.runtime_dir / "bin" / binary_name

        try:
            decky.logger.info(f"Downloading llamafile binary from: {binary_url}")

            def _download():
                import urllib.request
                import ssl
                import shutil
                import stat

                binary_path.parent.mkdir(parents=True, exist_ok=True)
                temp_path = binary_path.with_suffix('.tmp')

                context = ssl._create_unverified_context()

                # Add browser-like User-Agent for GitHub/CDN compatibility
                headers = {
                    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                }
                req = urllib.request.Request(binary_url, headers=headers)

                with urllib.request.urlopen(req, context=context) as response:
                    total_size = int(response.headers.get('content-length', 0))
                    decky.logger.info(f"Download size: {total_size / 1024 / 1024:.1f} MB")

                    with open(temp_path, 'wb') as f:
                        shutil.copyfileobj(response, f)

                temp_path.rename(binary_path)
                binary_path.chmod(stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
                return str(binary_path)

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(self.executor, _download)

            decky.logger.info(f"Binary downloaded to: {binary_path}")
            return True

        except Exception as e:
            decky.logger.error(f"Binary download failed: {e}")
            if binary_path.with_suffix('.tmp').exists():
                binary_path.with_suffix('.tmp').unlink()
            return False

    async def load_model(self) -> tuple:
        """
        Initialize the LLM subprocess wrapper.
        Returns tuple (success: bool, error_reason: str or None).
        """
        decky.logger.info("="*60)
        decky.logger.info("load_model: STARTING MODEL LOAD")
        decky.logger.info("="*60)

        # Check dependencies
        decky.logger.info("Checking dependencies...")
        deps_status = self.check_dependencies()
        missing_deps = [name for name, status in deps_status.items() if not status["available"]]
        if missing_deps:
            decky.logger.error(f"Missing dependencies: {', '.join(missing_deps)}")
            decky.logger.error("This indicates a bundling issue. The plugin may need to be reinstalled.")
        else:
            decky.logger.info("All dependencies available")

        # Check if model already loaded
        decky.logger.info("Checking existing model state...")
        if self._llm is not None:
            decky.logger.info("Model already loaded, skipping initialization")
            return (True, None)

        # Migrate Qwen model from old locations to new per-model directory structure
        qwen_filename = MODEL_CATALOG["qwen2.5-0.5b"]["filename"]
        qwen_final_path = self.model_dir / "qwen2.5-0.5b" / qwen_filename

        # From v1 flat layout: model_dir/filename -> model_dir/qwen2.5-0.5b/filename
        old_flat_path = self.model_dir / qwen_filename
        if old_flat_path.exists() and not qwen_final_path.exists():
            import shutil
            decky.logger.info("Migrating flat Qwen model to qwen2.5-0.5b/ directory")
            qwen_final_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old_flat_path), str(qwen_final_path))
            decky.logger.info("Migration complete")

        # From v2 llamafile/ layout: model_dir/llamafile/filename -> model_dir/qwen2.5-0.5b/filename
        old_llamafile_path = self.model_dir / "llamafile" / qwen_filename
        if old_llamafile_path.exists() and not qwen_final_path.exists():
            import shutil
            decky.logger.info("Migrating llamafile/ Qwen model to qwen2.5-0.5b/ directory")
            qwen_final_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old_llamafile_path), str(qwen_final_path))
            decky.logger.info("Migration complete")

        # Verify model file
        decky.logger.info(f"Verifying model file at {self.model_path}")
        model_exists = self.is_model_downloaded()
        decky.logger.info(f"Model file exists: {model_exists}")
        if model_exists:
            try:
                model_size_mb = self.model_path.stat().st_size / (1024 * 1024)
                decky.logger.info(f"Model size: {model_size_mb:.1f} MB")
            except Exception as e:
                decky.logger.warning(f"Could not determine model size: {e}")

        if not model_exists:
            decky.logger.error("Model not downloaded, cannot load")
            return (False, "model_not_downloaded")

        # Locate LLM binary
        decky.logger.info("Locating llamafile binary")

        binary_path = self._get_binary_path()
        if binary_path:
            decky.logger.info(f"Binary found: {binary_path} (type: llamafile)")
        else:
            decky.logger.warning("Llamafile binary not found, attempting to download...")
            download_success = await self.download_binary()
            if not download_success:
                plugin_dir = Path(PLUGIN_DIR)
                decky.logger.error("Llamafile binary download failed")
                decky.logger.error(f"Expected binary at: {plugin_dir}/bin/llamafile")
                return (False, "binary_not_found")

            binary_path = self._get_binary_path()
            if not binary_path:
                decky.logger.error("Binary still not found after download")
                return (False, "binary_download_failed")

        # Check system resources
        decky.logger.info("Checking system resources...")
        can_proceed, reason = self.resource_monitor.check_resources()
        resource_status = self.resource_monitor.get_status()
        decky.logger.info(f"Resource check result: can_proceed={can_proceed}")
        if not can_proceed:
            decky.logger.warning(f"Resource check failed: {reason}")
        decky.logger.info(f"Resource details: {resource_status}")

        if not can_proceed:
            decky.logger.warning(f"Cannot load model due to resource constraints: {reason}")
            return (False, f"resource_check_failed: {reason}")

        # Initialize subprocess
        try:
            decky.logger.info("Initializing llamafile subprocess wrapper...")
            decky.logger.info(f"  Binary: {binary_path}")
            decky.logger.info(f"  Model: {self.model_path}")

            from src.llama_inference import LlamaCppSubprocess
            self._llm = LlamaCppSubprocess(binary_path=str(binary_path), model_path=str(self.model_path))

            decky.logger.info("="*60)
            decky.logger.info("load_model: SUCCESS - llamafile subprocess wrapper initialized")
            decky.logger.info("="*60)
            return (True, None)

        except Exception as e:
            decky.logger.error("="*60)
            decky.logger.error(f"load_model: FAILED - Exception during initialization")
            decky.logger.error(f"Exception type: {type(e).__name__}")
            decky.logger.error(f"Exception message: {str(e)}")
            decky.logger.error("="*60)
            self.circuit_breaker.record_failure()
            return (False, f"init_exception: {str(e)}")

    def unload_model(self):
        """Unload the LLM model to free memory."""
        if self._llm is not None:
            del self._llm
            self._llm = None
            decky.logger.info("LLM model unloaded")

    def delete_model(self) -> bool:
        """Delete the downloaded model file."""
        try:
            # Unload first if loaded
            self.unload_model()

            # Delete model file
            if self.model_path.exists():
                self.model_path.unlink()
                decky.logger.info(f"Deleted model: {self.model_path}")

            # Clean up empty model directory
            if self.model_dir.exists() and not any(self.model_dir.iterdir()):
                self.model_dir.rmdir()

            return True
        except Exception as e:
            decky.logger.error(f"Failed to delete model: {e}")
            return False

    async def extract_article_text(self, url: str) -> Optional[str]:
        """
        Fetch and extract main text content from an article URL.
        Uses cloudscraper for Cloudflare bypass and readability-lxml for extraction.
        """
        try:
            def _extract():
                scraper = _get_cloudscraper().create_scraper(
                    browser={'browser': 'chrome', 'platform': 'linux', 'mobile': False}
                )

                response = scraper.get(url, timeout=10)
                response.raise_for_status()

                # Extract main content using readability-lxml (Mozilla Readability)
                Document = _get_readability()
                doc = Document(response.text)

                # Get cleaned text - readability returns HTML, strip tags
                summary_html = doc.summary()
                if summary_html:
                    # Simple HTML tag stripping using lxml
                    from lxml import html as lxml_html
                    text = lxml_html.fromstring(summary_html).text_content()
                    return text.strip() if text else None

                return None

            loop = asyncio.get_event_loop()
            text = await asyncio.wait_for(
                loop.run_in_executor(self.executor, _extract),
                timeout=self._get_active_config()["timeout_seconds"]
            )

            if text and len(text) > 100:
                # Truncate to max prompt length
                return text[:LLM_GLOBAL["max_prompt_chars"]]
            return None

        except asyncio.TimeoutError:
            decky.logger.warning(f"Article extraction timed out: {url}")
            return None
        except Exception as e:
            decky.logger.error(f"Article extraction failed: {e}")
            return None

    def _build_prompt(self, article_text: str) -> str:
        """Build ChatML prompt for Qwen model."""
        return (
            f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>\n"
            f"<|im_start|>user\nSummarize this article:\n\n{article_text}\n<|im_end|>\n"
            f"<|im_start|>assistant\n"
        )

    def _validate_output(self, output: str) -> Tuple[bool, str]:
        """
        Validate LLM output for hallucinations and quality.
        Returns: (is_valid, cleaned_output or error_message)
        """
        if not output or len(output.strip()) < 20:
            return False, "Output too short"

        # Check for common hallucination patterns
        hallucination_markers = [
            "I don't have access",
            "I cannot access",
            "I'm unable to",
            "As an AI language model",
            "As an AI assistant",
            "As an AI, I",
            "I apologize",
            "I'm sorry",
        ]

        for marker in hallucination_markers:
            if marker.lower() in output.lower():
                return False, f"Hallucination detected: {marker}"

        # Clean up output
        cleaned = output.strip()

        # Remove any trailing incomplete sentences
        if cleaned and not cleaned[-1] in '.!?':
            last_period = cleaned.rfind('.')
            if last_period > len(cleaned) // 2:
                cleaned = cleaned[:last_period + 1]

        return True, cleaned

    async def _start_idle_timeout_monitor(self):
        """Background task to monitor idle time and unload model."""
        import time

        while True:
            await asyncio.sleep(10)  # Check every 10 seconds

            if self._llm is None:
                continue

            if self._last_activity_time is None:
                continue

            idle_time = time.time() - self._last_activity_time

            if idle_time >= self._idle_timeout_seconds:
                decky.logger.info(f"[LLM] Idle timeout reached ({idle_time:.1f}s), unloading model")
                await self.unload_model()
                self._last_activity_time = None

    async def summarize_article(self, url: str, title: str = "", allow_during_gaming: bool = False) -> Dict:
        """
        Generate a summary for an article.

        Returns a dict with:
        - success: bool
        - summary: str (if successful)
        - error: str (if failed)
        - status: dict (rate limiter, resource status)
        """
        import time

        # Reset idle timer on activity
        self._last_activity_time = time.time()

        result = {
            "success": False,
            "summary": None,
            "error": None,
            "status": self.get_status()
        }

        # Check circuit breaker
        if not self.circuit_breaker.can_execute():
            result["error"] = "Service temporarily unavailable (circuit breaker open)"
            return result

        # Check thermal recovery bonus
        if self._thermal_bonus_until is not None and time.time() < self._thermal_bonus_until:
            remaining = self._thermal_bonus_until - time.time()
            decky.logger.info(f"[LLM] Thermal bonus active: {remaining:.0f}s remaining")
            result["error"] = f"Thermal recovery in progress: {remaining:.0f}s remaining"
            return result

        # Check rate limiter
        can_request, reason = self.rate_limiter.can_request()
        if not can_request:
            result["error"] = reason
            return result

        # Check resources
        can_proceed, reason = self.resource_monitor.check_resources()
        if not can_proceed:
            result["error"] = reason
            return result

        # Check if game is running
        if await is_game_running():
            if not allow_during_gaming:
                result["error"] = "Summarization blocked: game is running"
                return result

        # Ensure model is loaded
        success, error_reason = await self.load_model()
        if not success:
            diagnostics = self.get_load_diagnostics()
            decky.logger.error(f"LLM load failed: {error_reason}")
            decky.logger.error(f"Diagnostics: {diagnostics}")
            result["error"] = f"Failed to load LLM: {error_reason}"
            result["diagnostics"] = diagnostics
            return result

        try:
            # Extract article text with timing
            fetch_start = time.time()
            article_text = await self.extract_article_text(url)
            fetch_duration = time.time() - fetch_start

            if not article_text:
                result["error"] = "Failed to extract article content"
                self.circuit_breaker.record_failure()
                return result

            # Store article text and fetch timing for telemetry
            result["_article_text"] = article_text  # Internal: for telemetry only
            result["_fetch_duration"] = fetch_duration

            # Determine adaptive token budget
            active_cfg = self._get_active_config()
            soft_threshold = self.resource_monitor.max_temp_celsius - 5
            current_temp = self.resource_monitor._get_cpu_temperature()
            running_hot = current_temp is not None and current_temp > soft_threshold
            if self._adaptive_tokens_enabled and running_hot:
                effective_tokens = self._reduced_token_count
                decky.logger.info(f"[LLM] Adaptive tokens: {current_temp:.1f}°C > {soft_threshold}°C, using {effective_tokens} tokens")
            else:
                effective_tokens = active_cfg["max_gen_tokens"]

            # Determine adaptive thread count
            if self._adaptive_threads_enabled:
                effective_threads = await self.resource_monitor.get_adaptive_thread_count()
                if running_hot:
                    effective_threads = 1
                decky.logger.info(f"[LLM] Adaptive threads: {effective_threads} (hot={running_hot})")
            else:
                effective_threads = LLM_GLOBAL["n_threads"]

            # Run inference via subprocess with timeout
            def _inference():
                if active_cfg["prompt_format"] == "completion":
                    completion_prompt = (
                        f"Article: {article_text[:1000]}\n\nTL;DR:"
                    )
                    return self._llm.summarize(
                        article_text,
                        max_tokens=effective_tokens,
                        n_threads=effective_threads,
                        prompt_override=completion_prompt,
                        n_ctx=active_cfg["n_ctx"],
                    )
                else:
                    system_prompt = self._get_system_prompt(self.ai_personality)
                    return self._llm.summarize(
                        article_text,
                        max_tokens=effective_tokens,
                        system_prompt=system_prompt,
                        n_threads=effective_threads,
                        n_ctx=active_cfg["n_ctx"],
                        prompt_format=active_cfg["prompt_format"],
                    )

            loop = asyncio.get_event_loop()
            inference_result = await asyncio.wait_for(
                loop.run_in_executor(self.executor, _inference),
                timeout=active_cfg["timeout_seconds"]
            )

            # Extract summary text and metrics from result dict
            raw_summary = inference_result.get('summary', '')
            llm_metrics = {
                'tps': inference_result.get('tps'),
                'ttft': inference_result.get('ttft'),
                'prompt_eval_time': inference_result.get('prompt_eval_time'),
                'total_tokens': inference_result.get('total_tokens'),
                'stop_reason': inference_result.get('stop_reason', 'unknown'),
                'load_duration': inference_result.get('load_duration'),
            }

            # Validate output
            is_valid, processed = self._validate_output(raw_summary)

            if not is_valid:
                result["error"] = f"Output validation failed: {processed}"
                self.circuit_breaker.record_failure()
                return result

            # Success!
            self.circuit_breaker.record_success()
            self.rate_limiter.record_request()

            # Post-inference thermal bonus: extend cooldown if still hot
            post_temp = self.resource_monitor._get_cpu_temperature()
            if post_temp is not None and post_temp > soft_threshold and self._thermal_bonus_seconds > 0:
                self._thermal_bonus_until = time.time() + self._thermal_bonus_seconds
                decky.logger.info(f"[LLM] Thermal bonus set: {post_temp:.1f}°C, bonus={self._thermal_bonus_seconds}s")

            result["success"] = True
            result["summary"] = processed
            result["status"] = self.get_status()
            result["llm_metrics"] = llm_metrics  # Include metrics in response

            decky.logger.info(f"Generated summary for: {title or url}")
            return result

        except asyncio.TimeoutError:
            result["error"] = f"Inference timed out after {self._get_active_config()['timeout_seconds']}s"
            self.circuit_breaker.record_failure()
            return result
        except Exception as e:
            result["error"] = f"Summarization failed: {str(e)}"
            self.circuit_breaker.record_failure()
            decky.logger.error(f"Summarization error: {e}")
            return result

    def get_status(self) -> Dict:
        """Get comprehensive status of the summarization system."""
        cfg = self._get_active_config()
        return {
            "binary_available": self.is_binary_available(),
            "model_downloaded": self.is_model_downloaded(),
            "model_loaded": self._llm is not None,
            "model_loading": self._model_load_lock.locked(),
            "download_progress": self._download_progress,
            "selected_model": self.selected_model,
            "model_display_name": cfg["display_name"],
            "model_size_mb": cfg["size_mb"],
            "experimental": cfg.get("experimental", False),
            "circuit_breaker": self.circuit_breaker.get_status(),
            "rate_limiter": self.rate_limiter.get_status(),
            "resources": self.resource_monitor.get_status()
        }

    def get_load_diagnostics(self) -> Dict:
        """Return detailed diagnostics for debugging model loading issues."""
        binary_path = self._get_binary_path()
        plugin_dir = Path(PLUGIN_DIR)

        # List all binary candidates that were checked
        binary_candidates = [
            str(plugin_dir / "bin" / "llama-cli"),
            str(plugin_dir / "bin" / "main"),
            str(Path.home() / "homebrew" / "plugins" / "DeckyNews" / "bin" / "llama-cli"),
        ]

        # Check which candidates exist
        candidates_status = {}
        for candidate in binary_candidates:
            p = Path(candidate)
            candidates_status[candidate] = {
                "exists": p.exists(),
                "executable": os.access(candidate, os.X_OK) if p.exists() else False
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
            "binary_candidates_checked": candidates_status,
            "plugin_dir": str(PLUGIN_DIR),
            "runtime_dir": str(self.model_dir.parent),
            "dependencies": self.check_dependencies(),
        }

    def cleanup(self):
        """Cleanup resources on shutdown."""
        self.unload_model()
        self.executor.shutdown(wait=False)

class SettingsManager:
    def __init__(self, settings_dir: str):
        self.settings_path = Path(settings_dir) / "settings.json"
        self.settings = DEFAULT_SETTINGS.copy()

    def load(self) -> Dict:
        try:
            if self.settings_path.exists():
                with open(self.settings_path, 'r') as f:
                    loaded = json.load(f)
                    self.settings.update(loaded)
            else:
                self.save()
            return self.settings
        except Exception as e:
            decky.logger.error(f"Failed to load settings: {e}")
            return self.settings

    def save(self) -> bool:
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.settings_path.with_suffix('.tmp')
            with open(temp_path, 'w') as f:
                json.dump(self.settings, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            temp_path.replace(self.settings_path)
            return True
        except Exception as e:
            decky.logger.error(f"Failed to save settings: {e}")
            return False

    def update(self, new_settings: Dict) -> bool:
        self.settings.update(new_settings)
        return self.save()


class NewsFetcher:
    def __init__(self, db_manager: DatabaseManager, deduplicator: Optional[ArticleDeduplicator] = None):
        self.db = db_manager
        self.deduplicator = deduplicator
        self.source_health = {source: 'ok' for source in NEWS_SOURCES}
        self.failure_counts = {source: 0 for source in NEWS_SOURCES}
        self.last_fetch_times = {source: None for source in NEWS_SOURCES}
        self.backoff_delays = {source: 0 for source in NEWS_SOURCES}

    async def fetch_source(self, source_id: str, session: aiohttp.ClientSession) -> Optional[Dict]:
        if source_id not in NEWS_SOURCES:
            return None

        if self.backoff_delays[source_id] > 0:
            time_since_last = (datetime.now() - self.last_fetch_times[source_id]).total_seconds()
            if time_since_last < self.backoff_delays[source_id]:
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

            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15), headers=conditional_headers) as response:
                if response.status == 304:
                    self.source_health[source_id] = 'ok'
                    self.failure_counts[source_id] = 0
                    self.last_fetch_times[source_id] = datetime.now()
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
                feed = feedparser.parse(content)

                if not feed.entries:
                    raise Exception("No entries in feed")

                articles = []
                for entry in feed.entries[:20]:
                    published = entry.get('published_parsed') or entry.get('updated_parsed')
                    if published:
                        pub_datetime = datetime(*published[:6])
                    else:
                        pub_datetime = datetime.now()

                    articles.append({
                        'title': entry.get('title', 'No title'),
                        'link': entry.get('link', ''),
                        'published': pub_datetime.isoformat() + 'Z',
                        'source': source_id,
                        'content': entry.get('summary', ''),
                        'image_url': get_static_logo_url(source_id),
                        'favicon_url': favicon_url,
                    })

                # Insert articles into database
                result = await asyncio.get_event_loop().run_in_executor(None, self.db.insert_articles, articles)

                self.source_health[source_id] = 'ok'
                self.failure_counts[source_id] = 0
                self.backoff_delays[source_id] = 0
                self.last_fetch_times[source_id] = datetime.now()

                decky.logger.info(
                    f"Successfully fetched {len(articles)} articles from {source_id} "
                    f"({result['inserted']} new, {result['duplicates']} duplicates)"
                )
                return {'source': source_id, 'articles': articles, 'result': result}

        except Exception as e:
            self.failure_counts[source_id] += 1
            self.backoff_delays[source_id] = min(300, 30 * (2 ** self.failure_counts[source_id]))
            self.last_fetch_times[source_id] = datetime.now()

            if self.failure_counts[source_id] >= 3:
                self.source_health[source_id] = 'error'
            else:
                self.source_health[source_id] = 'warning'

            decky.logger.error(f"Failed to fetch {source_id}: {e}")
            return None

    async def fetch_all_sources(self, enabled_sources: List[str]) -> int:
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        connector = aiohttp.TCPConnector(ssl=ssl_context, limit=30, limit_per_host=3, ttl_dns_cache=300)

        headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }

        async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
            tasks = []
            for source_id in enabled_sources:
                if source_id in NEWS_SOURCES:
                    tasks.append(self.fetch_source(source_id, session))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            successful = sum(1 for r in results if r is not None and not isinstance(r, Exception))

            return successful

class Plugin:
    def _load_news_sources(self):
        """
        Load news sources from sources.json in plugin settings directory.
        Falls back to CONST_DEFAULT_SOURCES if file doesn't exist or fails to load.

        Expected sources.json format:
        {
            "IGN": "https://feeds.feedburner.com/ign/all",
            "PCGamer": "https://www.pcgamer.com/rss/",
            ...
        }
        """
        global NEWS_SOURCES

        sources_file = Path(decky.DECKY_PLUGIN_SETTINGS_DIR) / "sources.json"

        try:
            if sources_file.exists():
                with open(sources_file, 'r', encoding='utf-8') as f:
                    loaded_sources = json.load(f)

                # Validate format (must be dict with string values)
                if isinstance(loaded_sources, dict) and all(
                    isinstance(k, str) and isinstance(v, str)
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

        # Fallback to defaults
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

    async def _migrate_from_json_to_sqlite(self):
        """
        One-time migration: Delete old JSON cache files.
        No data preservation needed per architecture plan.
        """
        cache_dir = Path(decky.DECKY_PLUGIN_RUNTIME_DIR) / "cache"

        if cache_dir.exists():
            decky.logger.info("[Migration] Removing old JSON cache files")

            try:
                for json_file in cache_dir.glob("*.json"):
                    json_file.unlink()
                    decky.logger.debug(f"[Migration] Deleted {json_file.name}")

                cache_dir.rmdir()
                decky.logger.info("[Migration] JSON cache deleted successfully")
            except Exception as e:
                decky.logger.warning(f"[Migration] Failed to delete cache: {e}")

    async def _main(self):
        self.settings_manager = SettingsManager(decky.DECKY_PLUGIN_SETTINGS_DIR)

        # Load news sources from sources.json (or use defaults)
        self._load_news_sources()

        # Migrate from JSON cache to SQLite database
        await self._migrate_from_json_to_sqlite()

        # Initialize database manager
        self.db_manager = DatabaseManager(decky.DECKY_PLUGIN_RUNTIME_DIR)

        # Initialize deduplicator if enabled
        self.settings = self.settings_manager.load()
        dedup_enabled = self.settings.get("deduplicationEnabled", True)
        dedup_threshold = self.settings.get("deduplicationThreshold", 10)
        self.deduplicator = ArticleDeduplicator(dedup_threshold) if dedup_enabled else None

        # Initialize news fetcher with database
        self.news_fetcher = NewsFetcher(self.db_manager, self.deduplicator)

        # Get resource monitoring settings for LLM

        # Initialize LLM summarization manager with resource monitoring setting
        resource_monitoring = self.settings.get("llmResourceMonitoringEnabled", True)
        cooldown_seconds = self.settings.get("llmCooldownSeconds", 20)
        idle_timeout_seconds = self.settings.get("llmIdleTimeoutSeconds", 60)
        ai_personality = self.settings.get("aiPersonality", "analyst")
        self.summarization_manager = SummarizationManager(
            decky.DECKY_PLUGIN_RUNTIME_DIR,
            resource_monitoring_enabled=resource_monitoring,
            cooldown_seconds=cooldown_seconds,
            idle_timeout_seconds=idle_timeout_seconds,
            ai_personality=ai_personality,
            temp_ceiling=self.settings.get("llmTempCeilingCelsius", 75),
            thermal_cooldown_bonus=self.settings.get("llmThermalCooldownBonus", 30),
            adaptive_tokens=self.settings.get("llmAdaptiveTokens", True),
            reduced_token_count=self.settings.get("llmReducedTokenCount", 80),
            adaptive_threads=self.settings.get("llmAdaptiveThreads", True),
            selected_model=self.settings.get("selectedModel", "qwen2.5-0.5b"),
        )

        # Initialize telemetry system
        telemetry_db_path = Path(decky.DECKY_PLUGIN_RUNTIME_DIR) / "telemetry.db"
        from src.telemetry import TelemetryManager
        self.telemetry = TelemetryManager(telemetry_db_path, plugin_instance=self)

        self.refresh_task = None
        self.idle_monitor_task = None

        decky.logger.info(f"DeckyNews initialized (with LLM support, resource monitoring: {resource_monitoring})")

        enabled_sources = self.settings.get('sourcesEnabled', [])
        decky.logger.info(f"Scheduling initial fetch for sources: {enabled_sources}")

        self.loop = asyncio.get_event_loop()

        # Start idle timeout monitor for LLM
        self.idle_monitor_task = self.loop.create_task(
            self.summarization_manager._start_idle_timeout_monitor()
        )

        self.refresh_task = self.loop.create_task(self._initial_fetch_and_refresh_loop())

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
            enabled_sources = self.settings.get('sourcesEnabled', [])
            decky.logger.info(f"Performing initial fetch for sources: {enabled_sources}")
            successful = await self.news_fetcher.fetch_all_sources(enabled_sources)
            decky.logger.info(f"Initial fetch completed: {successful}/{len(enabled_sources)} sources successful")
        except Exception as e:
            decky.logger.error(f"Initial fetch failed: {e}")

        while True:
            try:
                interval_minutes = self.settings.get('refreshInterval', 30)
                await asyncio.sleep(interval_minutes * 60)

                enabled_sources = self.settings.get('sourcesEnabled', [])
                await self.news_fetcher.fetch_all_sources(enabled_sources)

                # Run deduplication if enabled
                if self.deduplicator:
                    articles = self.db_manager.get_all_articles_for_deduplication(max_articles=500)
                    groups = self.deduplicator.find_duplicates(articles)
                    if groups:
                        self.deduplicator.mark_duplicates_in_db(self.db_manager, groups)

                # Database maintenance (vacuum old articles)
                if self.settings.get("autoVacuumEnabled", True):
                    await asyncio.get_event_loop().run_in_executor(None, self.db_manager.vacuum_old_articles)

                await decky.emit("news_refreshed", {"timestamp": datetime.now().isoformat()})

            except asyncio.CancelledError:
                break
            except Exception as e:
                decky.logger.error(f"Background refresh error: {e}")
                await asyncio.sleep(60)

    async def _unload(self):
        if self.refresh_task:
            self.refresh_task.cancel()
            try:
                await self.refresh_task
            except asyncio.CancelledError:
                pass

        # Stop idle timeout monitor
        if hasattr(self, 'idle_monitor_task') and self.idle_monitor_task:
            self.idle_monitor_task.cancel()
            try:
                await self.idle_monitor_task
            except asyncio.CancelledError:
                pass

        # Cleanup LLM resources
        if hasattr(self, 'summarization_manager'):
            self.summarization_manager.cleanup()

        # Close database connection
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
            enabled_sources = self.settings.get('sourcesEnabled', [])

            # Get paginated articles from database
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
            enabled_sources = self.settings.get('sourcesEnabled', [])
            decky.logger.info(f"Manual refresh triggered for sources: {enabled_sources}")

            successful = await self.news_fetcher.fetch_all_sources(enabled_sources)
            decky.logger.info(f"Manual refresh completed: {successful}/{len(enabled_sources)} sources successful")

            # Run deduplication if enabled
            if self.deduplicator:
                articles = self.db_manager.get_all_articles_for_deduplication(max_articles=500)
                groups = self.deduplicator.find_duplicates(articles)
                if groups:
                    self.deduplicator.mark_duplicates_in_db(self.db_manager, groups)
                    decky.logger.info(f"Deduplication: found {len(groups)} duplicate groups")

            # Vacuum old articles (30+ days) and run VACUUM if needed
            if self.settings.get("autoVacuumEnabled", True):
                vacuum_result = self.db_manager.vacuum_old_articles()
                if vacuum_result['deleted_count'] > 0 or vacuum_result['vacuumed']:
                    decky.logger.info(
                        f"Database maintenance: deleted {vacuum_result['deleted_count']} old articles, "
                        f"vacuumed: {vacuum_result['vacuumed']}"
                    )

            await decky.emit("news_refreshed", {"timestamp": datetime.now().isoformat()})

            result = successful > 0
            decky.logger.info(f"Refresh result: {result} (returning to frontend)")
            return result
        except Exception as e:
            decky.logger.error(f"Failed to refresh news: {e}")
            return False

    async def get_settings(self) -> Dict:
        return self.settings

    async def update_settings(self, new_settings: Dict) -> bool:
        try:
            result = self.settings_manager.update(new_settings)
            if result:
                self.settings = self.settings_manager.settings

                # Update rate limiter cooldown if changed
                if "llmCooldownSeconds" in new_settings:
                    cooldown = new_settings["llmCooldownSeconds"]
                    self.summarization_manager.rate_limiter.update_cooldown(cooldown)

                # Update AI personality if changed
                if "aiPersonality" in new_settings:
                    personality = new_settings["aiPersonality"]
                    self.summarization_manager.set_ai_personality(personality)

                # Switch model if changed (unloads current model automatically)
                if "selectedModel" in new_settings:
                    self.summarization_manager.set_selected_model(new_settings["selectedModel"])

                # Update thermal guardrail settings if changed
                if "llmTempCeilingCelsius" in new_settings:
                    self.summarization_manager.resource_monitor.max_temp_celsius = new_settings["llmTempCeilingCelsius"]

                if "llmThermalCooldownBonus" in new_settings:
                    self.summarization_manager._thermal_bonus_seconds = new_settings["llmThermalCooldownBonus"]

                if "llmAdaptiveTokens" in new_settings:
                    self.summarization_manager._adaptive_tokens_enabled = new_settings["llmAdaptiveTokens"]

                if "llmReducedTokenCount" in new_settings:
                    self.summarization_manager._reduced_token_count = new_settings["llmReducedTokenCount"]

                if "llmAdaptiveThreads" in new_settings:
                    self.summarization_manager._adaptive_threads_enabled = new_settings["llmAdaptiveThreads"]

            return result
        except Exception as e:
            decky.logger.error(f"Failed to update settings: {e}")
            return False

    async def get_source_health(self) -> Dict:
        return self.news_fetcher.source_health

    async def summarize_article(self, url: str, title: str = "") -> Dict:
        """
        Generate an AI summary for an article.
        Called from frontend when user clicks summarize button.
        """
        if not self.settings.get('llmEnabled', False):
            return {
                "success": False,
                "error": "LLM summarization is disabled. Enable it in settings.",
                "summary": None,
                "status": None
            }

        session_id = self.telemetry.start_session(url, model_id=self.summarization_manager.selected_model)

        start_time = time.perf_counter()
        result = await self.summarization_manager.summarize_article(
            url, title,
            allow_during_gaming=self.settings.get("allowLlmDuringGaming", False)
        )
        total_duration = time.perf_counter() - start_time

        if session_id:
            self.telemetry.record_hardware(session_id)

        if session_id and result.get('success'):
            fetch_duration = result.get('_fetch_duration')
            if fetch_duration:
                self.telemetry.record_timing(session_id, "fetch", fetch_duration)

            self.telemetry.record_timing(session_id, "inference", total_duration)

            llm_metrics = result.get('llm_metrics', {})

            summary_result = {
                'summary': result.get('summary', ''),
                'original_text': result.get('_article_text', ''),
                'tps': llm_metrics.get('tps'),
                'ttft': llm_metrics.get('ttft'),
                'prompt_eval_time': llm_metrics.get('prompt_eval_time'),
                'total_tokens': llm_metrics.get('total_tokens'),
                'stop_reason': llm_metrics.get('stop_reason'),
                'load_duration': llm_metrics.get('load_duration'),
            }

            self.telemetry.finalize_session(session_id, summary_result, article_url=url)

        # Remove internal telemetry fields before returning to frontend
        result.pop('_article_text', None)
        result.pop('_fetch_duration', None)

        return result

    async def get_llm_status(self) -> Dict:
        """Get current status of the LLM summarization system."""
        return {
            "enabled": self.settings.get('llmEnabled', False),
            **self.summarization_manager.get_status(),
            "diagnostics": self.summarization_manager.get_load_diagnostics()
        }

    async def download_llm_model(self) -> Dict:
        """
        Trigger LLM model download.
        Called when user enables LLM for the first time.
        """
        try:
            if not self.summarization_manager.is_binary_available():
                await self.summarization_manager.download_binary()
            success = await self.summarization_manager.download_model()
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
        """Unload the LLM model to free memory."""
        try:
            self.summarization_manager.unload_model()
            return True
        except Exception as e:
            decky.logger.error(f"Failed to unload model: {e}")
            return False

    async def delete_llm_model(self) -> bool:
        """Delete the downloaded LLM model."""
        try:
            return self.summarization_manager.delete_model()
        except Exception as e:
            decky.logger.error(f"Failed to delete model: {e}")
            return False

    async def get_coverage_sparkline(self, similarity_hash: str) -> Dict:
        """
        Get 24-hour coverage trend for a similarity group.
        Used for sparkline visualization on frontend.

        Args:
            similarity_hash: The similarity hash of the article group

        Returns:
            Dict with 'points' (list of {hour, count, normalized}) and 'max_count'
        """
        try:
            return self.db_manager.get_coverage_sparkline(similarity_hash)
        except Exception as e:
            decky.logger.error(f"Failed to get coverage sparkline: {e}")
            return {'points': [], 'max_count': 0}

    async def get_telemetry_heatmap(self, hours: int = 6) -> Dict:
        """
        Fetch telemetry heatmap data for last N hours.

        Args:
            hours: Number of hours to fetch (default 6 for 12x5 grid)

        Returns:
            Dict with 'success' and 'data' (list of session metrics)
        """
        try:
            data = self.telemetry.db.get_heatmap_data(hours)
            return {"success": True, "data": data}
        except Exception as e:
            decky.logger.error(f"Telemetry fetch failed: {e}")
            return {"success": False, "error": str(e)}

    async def export_telemetry_dossier(self) -> Dict:
        """
        Generate human-readable .txt dossier.

        Returns:
            Dict with 'success' and 'path' (file location)
        """
        try:
            # Save to Documents folder if it exists, otherwise use plugin runtime dir
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
        """
        Wipe all telemetry records (admin function).

        Returns:
            Dict with 'success' status
        """
        try:
            self.telemetry.db.clear_all_records()
            return {"success": True}
        except Exception as e:
            decky.logger.error(f"Telemetry clear failed: {e}")
            return {"success": False, "error": str(e)}


