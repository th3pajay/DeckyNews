import logging
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(ROOT))
# Vendored deps are Linux builds; keep them behind the host's own packages.
sys.path.append(str(ROOT / "py_modules"))

try:
    import psutil  # noqa: F401  (bind the host build before main.py prepends py_modules)
except ImportError:
    pass

_decky = types.ModuleType("decky")
_decky.logger = logging.getLogger("decky-test")
_decky.DECKY_PLUGIN_DIR = str(ROOT)
_decky.DECKY_PLUGIN_SETTINGS_DIR = str(ROOT / ".test-settings")
_decky.DECKY_PLUGIN_RUNTIME_DIR = str(ROOT / ".test-runtime")
sys.modules.setdefault("decky", _decky)


class FakeHardware:
    def __init__(self, temp=50.0, available_mb=2000.0, percent_used=40.0, game=False):
        self.temp = temp
        self.available_mb = available_mb
        self.percent_used = percent_used
        self.game = game

    def cpu_temperature(self):
        if isinstance(self.temp, Exception):
            raise self.temp
        return self.temp

    def memory(self):
        if isinstance(self.available_mb, Exception):
            raise self.available_mb
        return self.available_mb, self.percent_used

    async def game_running(self):
        return self.game


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def hw():
    return FakeHardware()


@pytest.fixture
def clock():
    return FakeClock()
