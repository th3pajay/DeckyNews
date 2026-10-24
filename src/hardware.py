import asyncio
import logging
import subprocess
from typing import Optional, Tuple

_log = logging.getLogger("hardware")

_TEMP_PATHS = (
    "/sys/class/hwmon/hwmon0/temp1_input",
    "/sys/class/hwmon/hwmon1/temp1_input",
    "/sys/class/thermal/thermal_zone0/temp",
)

_psutil = None


def get_psutil():
    global _psutil
    if _psutil is None:
        import psutil
        _psutil = psutil
    return _psutil


async def is_game_running() -> bool:
    try:
        proc = await asyncio.create_subprocess_exec(
            'pgrep', '-f', 'reaper SteamLaunch',
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        await proc.wait()
        return proc.returncode == 0
    except Exception as e:
        _log.debug(f"Game detection failed: {e}")

        return False


class SystemHardware:
    def cpu_temperature(self) -> Optional[float]:
        for path in _TEMP_PATHS:
            try:
                with open(path, 'r') as f:
                    return int(f.read().strip()) / 1000
            except (FileNotFoundError, ValueError, PermissionError):
                continue

        try:
            temps = get_psutil().sensors_temperatures()
            if temps:
                for entries in temps.values():
                    for entry in entries:
                        if entry.current:
                            return entry.current
        except Exception:
            pass
        return None

    def memory(self) -> Tuple[float, float]:
        mem = get_psutil().virtual_memory()
        return mem.available / (1024 * 1024), mem.percent

    async def game_running(self) -> bool:
        return await is_game_running()
