"""Persistent user settings for checkit (shared by the GUI and the CLI).

Settings — including API keys — are stored as JSON in a per-user config
directory. The file is created with user-only permissions (0600) on POSIX
systems. Set the CHECKIT_SETTINGS environment variable to override the
location (used by tests and portable setups).
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass
class Settings:
    url: str = ""
    out_dir: str = "checkit-out"
    max_pages: int = 100
    delay: float = 1.0
    fmt: str = "markdown"
    use_llm: bool = True
    provider: str = "mistral"
    model: str = ""
    verbose: bool = False
    api_keys: dict = None  # provider -> key; never logged or printed

    def __post_init__(self):
        if self.api_keys is None:
            self.api_keys = {}
        if not isinstance(self.api_keys, dict):
            self.api_keys = {}

    @classmethod
    def from_dict(cls, data) -> "Settings":
        if not isinstance(data, dict):
            return cls()
        kwargs = {}
        for f in fields(cls):
            if f.name in data:
                kwargs[f.name] = data[f.name]
        return cls(**kwargs)

    def to_dict(self) -> dict:
        return asdict(self)

    def api_key_for(self, provider: str):
        return self.api_keys.get(provider)


def settings_path() -> Path:
    """Return the settings file location for this platform."""
    override = os.environ.get("CHECKIT_SETTINGS")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return base / "checkit" / "settings.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "checkit" / "settings.json"
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "checkit" / "settings.json"


def load_settings(path=None) -> Settings:
    """Load settings; returns defaults if the file is missing or corrupt."""
    p = Path(path) if path else settings_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return Settings.from_dict(data)
    except (OSError, ValueError):
        return Settings()


def save_settings(settings: Settings, path=None) -> Path:
    """Persist settings. Returns the path written.

    The file is created with user-only permissions on POSIX systems because
    it may contain API keys.
    """
    p = Path(path) if path else settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(settings.to_dict(), indent=2) + "\n",
                 encoding="utf-8")
    if os.name == "posix":
        p.chmod(0o600)
    return p
