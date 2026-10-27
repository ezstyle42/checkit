import pytest

from checkit.llm import (
    ENV_KEYS,
    LLMClient,
    KeyNotFoundError,
    load_env_file,
    resolve_api_key,
)


class TestResolveApiKey:
    def test_explicit_key_wins(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY", "env-key")
        assert resolve_api_key("mistral", explicit="arg-key") == "arg-key"

    def test_env_var(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "env-key")
        assert resolve_api_key("openai") == "env-key"

    def test_env_file(self, monkeypatch, tmp_path):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        env_file = tmp_path / "checkit.env"
        env_file.write_text(
            "# comment\nANTHROPIC_API_KEY=file-key\nMISTRAL_API_KEY=\"quoted\"\n"
        )
        assert resolve_api_key("claude", env_file=str(env_file)) == "file-key"
        assert resolve_api_key("mistral", env_file=str(env_file)) == "quoted"

    def test_missing_key_raises(self, monkeypatch, tmp_path):
        for name in ENV_KEYS.values():
            monkeypatch.delenv(name, raising=False)
        with pytest.raises(KeyNotFoundError):
            resolve_api_key("openai", env_file=str(tmp_path / "nope.env"))

    def test_unknown_provider(self):
        with pytest.raises(ValueError):
            resolve_api_key("gemini")


class TestLoadEnvFile:
    def test_parsing(self, tmp_path):
        f = tmp_path / "checkit.env"
        f.write_text("A=1\n\n# c\nB='two'\nbad line\n")
        assert load_env_file(str(f)) == {"A": "1", "B": "two"}

    def test_missing_file(self, tmp_path):
        assert load_env_file(str(tmp_path / "nope")) == {}


class FakePoster:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def __call__(self, url, headers, payload):
        self.calls.append((url, headers, payload))
        return self.response


class TestLLMClient:
    def test_openai_payload_and_parse(self):
        poster = FakePoster({
            "choices": [{"message": {"content": "hello"}}]
        })
        client = LLMClient("openai", api_key="k", poster=poster)
        resp = client.complete("sys", "usr")
        assert resp.text == "hello"
        url, headers, payload = poster.calls[0]
        assert url == "https://api.openai.com/v1/chat/completions"
        assert headers["Authorization"] == "Bearer k"
        assert payload["messages"][0] == {"role": "system", "content": "sys"}
        assert payload["messages"][1] == {"role": "user", "content": "usr"}

    def test_claude_payload_and_parse(self):
        poster = FakePoster({
            "content": [{"type": "text", "text": "part1"},
                        {"type": "text", "text": "part2"}]
        })
        client = LLMClient("claude", api_key="k", poster=poster)
        resp = client.complete("sys", "usr")
        assert resp.text == "part1part2"
        url, headers, payload = poster.calls[0]
        assert url == "https://api.anthropic.com/v1/messages"
        assert headers["x-api-key"] == "k"
        assert payload["system"] == "sys"
        assert payload["messages"] == [{"role": "user", "content": "usr"}]

    def test_mistral_uses_bearer(self):
        poster = FakePoster({"choices": [{"message": {"content": "ok"}}]})
        client = LLMClient("mistral", api_key="k", poster=poster)
        client.complete("s", "u")
        _url, headers, _payload = poster.calls[0]
        assert headers["Authorization"] == "Bearer k"

    def test_default_models(self):
        assert LLMClient("openai", api_key="k", poster=FakePoster({})).model
        assert LLMClient("mistral", api_key="k", poster=FakePoster({})).model
        assert LLMClient("claude", api_key="k", poster=FakePoster({})).model
