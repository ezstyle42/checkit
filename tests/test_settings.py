import json
import os
import stat

import pytest

from checkit.settings import Settings, load_settings, save_settings, settings_path


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("CHECKIT_SETTINGS", str(tmp_path / "settings.json"))
    yield tmp_path / "settings.json"


class TestSettingsPath:
    def test_env_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CHECKIT_SETTINGS", str(tmp_path / "custom.json"))
        assert settings_path() == tmp_path / "custom.json"

    def test_platform_default(self, monkeypatch):
        monkeypatch.delenv("CHECKIT_SETTINGS", raising=False)
        p = settings_path()
        assert "checkit" in str(p)
        assert p.name == "settings.json"


class TestRoundTrip:
    def test_defaults_when_missing(self):
        s = load_settings()
        assert s.max_pages == 100
        assert s.provider == "mistral"
        assert s.api_keys == {}

    def test_save_and_load(self):
        s = Settings(url="https://x.example", out_dir="/tmp/out",
                     max_pages=42, delay=0.5, fmt="xml", use_llm=False,
                     provider="openai", model="gpt-4o", verbose=True,
                     api_keys={"openai": "sk-secret123"})
        path = save_settings(s)
        assert path.exists()
        loaded = load_settings()
        assert loaded.url == "https://x.example"
        assert loaded.max_pages == 42
        assert loaded.delay == 0.5
        assert loaded.fmt == "xml"
        assert loaded.use_llm is False
        assert loaded.verbose is True
        assert loaded.api_key_for("openai") == "sk-secret123"
        assert loaded.api_key_for("mistral") is None

    def test_file_permissions_are_user_only(self):
        if os.name != "posix":
            pytest.skip("POSIX-only check")
        path = save_settings(Settings(api_keys={"mistral": "sk-x"}))
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode == 0o600

    def test_corrupt_file_returns_defaults(self, isolated_settings):
        isolated_settings.write_text("{not json")
        s = load_settings()
        assert s.max_pages == 100

    def test_from_dict_ignores_unknown_keys(self):
        s = Settings.from_dict({"url": "https://x", "bogus": 1, "max_pages": 5})
        assert s.url == "https://x"
        assert s.max_pages == 5
        assert not hasattr(s, "bogus")


class TestApiKeyFor:
    def test_missing_provider(self):
        assert Settings().api_key_for("claude") is None


class TestApiKeyResolutionFromSettings:
    def test_resolve_api_key_falls_back_to_saved_settings(self, monkeypatch):
        for var in ("MISTRAL_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
            monkeypatch.delenv(var, raising=False)
        save_settings(Settings(api_keys={"openai": "sk-from-settings"}))
        from checkit.llm import resolve_api_key
        assert resolve_api_key("openai", env_file="/nonexistent.env") == "sk-from-settings"

    def test_explicit_key_beats_saved_settings(self, monkeypatch):
        for var in ("MISTRAL_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
            monkeypatch.delenv(var, raising=False)
        save_settings(Settings(api_keys={"openai": "sk-from-settings"}))
        from checkit.llm import resolve_api_key
        assert resolve_api_key("openai", explicit="sk-explicit",
                               env_file="/nonexistent.env") == "sk-explicit"

    def test_env_var_beats_saved_settings(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
        save_settings(Settings(api_keys={"openai": "sk-from-settings"}))
        from checkit.llm import resolve_api_key
        assert resolve_api_key("openai", env_file="/nonexistent.env") == "sk-from-env"

    def test_missing_everywhere_raises(self, monkeypatch):
        for var in ("MISTRAL_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
            monkeypatch.delenv(var, raising=False)
        from checkit.llm import KeyNotFoundError, resolve_api_key
        with pytest.raises(KeyNotFoundError):
            resolve_api_key("claude", env_file="/nonexistent.env")
