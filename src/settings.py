import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_SETTINGS: Dict[str, Any] = {
    "refreshInterval": 30,
    "debugMode": False,
    "sourcesEnabled": ["IGN", "PCGamer", "Steam", "Kotaku", "GameSpot", "Polygon"],
    "analyticsOptIn": False,
    "llmEnabled": False,
    "llmResourceMonitoringEnabled": True,
    "llmCooldownSeconds": 20,

    "llmIdleTimeoutSeconds": 60,
    "deduplicationEnabled": True,
    "deduplicationThreshold": 10,
    "autoVacuumEnabled": True,

    "showSourceIcons": True,
    "aiTypewriterEnabled": True,
    "aiTypewriterSpeed": 30,

    "hoverPreviewDelay": 700,

    "aiPersonality": "analyst",

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


def _type_ok(default: Any, value: Any) -> bool:

    if isinstance(default, bool) or isinstance(value, bool):
        return isinstance(default, bool) and isinstance(value, bool)
    return isinstance(value, type(default))


class SettingsManager:
    def __init__(self, settings_dir: str, logger: Optional[logging.Logger] = None):
        self.settings_path = Path(settings_dir) / "settings.json"
        self.settings = DEFAULT_SETTINGS.copy()
        self._log = logger or logging.getLogger("settings")

    def get(self, key: str) -> Any:
        return self.settings.get(key, DEFAULT_SETTINGS.get(key))

    def load(self) -> Dict:
        if not self.settings_path.exists():
            self.save()
            return self.settings
        try:
            with open(self.settings_path, 'r') as f:
                self.settings.update(json.load(f))
        except json.JSONDecodeError as e:


            backup = self.settings_path.with_name(self.settings_path.name + ".corrupt")
            try:
                self.settings_path.replace(backup)
                self._log.error(f"settings.json is corrupt ({e}); backed up to {backup.name}, using defaults")
            except OSError as move_err:
                self._log.error(f"settings.json is corrupt and could not be backed up: {move_err}")
        except OSError as e:
            self._log.error(f"Failed to read settings: {e}")
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
            self._log.error(f"Failed to save settings: {e}")
            return False

    def update(self, new_settings: Dict) -> Optional[Dict]:
        for key, value in new_settings.items():
            if key not in DEFAULT_SETTINGS:
                self._log.warning(f"Rejected settings update: unknown key '{key}'")
                return None
            if not _type_ok(DEFAULT_SETTINGS[key], value):
                self._log.warning(f"Rejected settings update: bad type for '{key}': {type(value).__name__}")
                return None
        self.settings.update(new_settings)
        return dict(new_settings) if self.save() else None
