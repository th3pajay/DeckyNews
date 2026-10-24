import logging
from pathlib import Path
from typing import Optional


def drop_json_cache(runtime_dir: Path, logger: Optional[logging.Logger] = None) -> None:
    log = logger or logging.getLogger("migrations")
    marker = runtime_dir / ".json_cache_migrated"
    if marker.exists():
        return

    cache_dir = runtime_dir / "cache"
    if cache_dir.exists():
        log.info("[Migration] Removing old JSON cache files")
        try:
            for json_file in cache_dir.glob("*.json"):
                json_file.unlink()
            cache_dir.rmdir()
            log.info("[Migration] JSON cache deleted successfully")
        except OSError as e:
            log.warning(f"[Migration] Failed to delete cache, will retry next start: {e}")
            return

    try:
        marker.touch()
    except OSError:
        pass
