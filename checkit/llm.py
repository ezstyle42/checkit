"""Minimal multi-provider LLM client: Mistral, OpenAI and Claude (Anthropic).

API keys are resolved from (in order): explicit argument, environment
variable, or a `checkit.env` file next to the current working directory.
No SDK dependencies are required; plain HTTP via `requests`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import requests

ENV_KEYS = {
    "mistral": "MISTRAL_API_KEY",
    "openai": "OPENAI_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
}

PROVIDERS = ("mistral", "openai", "claude")

DEFAULT_MODELS = {
    "mistral": "mistral-large-latest",
    "openai": "gpt-4o-mini",
    "claude": "claude-sonnet-4-5",
}

ENDPOINTS = {
    "mistral": "https://api.mistral.ai/v1/chat/completions",
    "openai": "https://api.openai.com/v1/chat/completions",
    "claude": "https://api.anthropic.com/v1/messages",
}

MAX_COMPLETION_TOKENS = {
    "mistral": "max_tokens",
    "openai": "max_tokens",
    "claude": "max_tokens",
}


class KeyNotFoundError(RuntimeError):
    pass


def load_env_file(path="checkit.env") -> dict:
    """Parse a simple KEY=VALUE env file. Returns dict of parsed values."""
    values = {}
    p = Path(path)
    if not p.is_file():
        return values
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def resolve_api_key(provider: str, explicit: str | None = None,
                    env_file: str = "checkit.env") -> str:
    """Resolve an API key for a provider from arg > env var > env file."""
    provider = provider.lower()
    if provider not in ENV_KEYS:
        raise ValueError(f"Unknown provider {provider!r}. Choose from {PROVIDERS}")
    if explicit:
        return explicit
    env_name = ENV_KEYS[provider]
    key = os.environ.get(env_name)
    if key:
        return key
    key = load_env_file(env_file).get(env_name)
    if key:
        return key
    raise KeyNotFoundError(
        f"No API key for provider {provider!r}. Set ${env_name}, pass --api-key, "
        f"or add {env_name}=... to {env_file}."
    )


@dataclass
class LLMResponse:
    provider: str
    model: str
    text: str
    raw: dict


class LLMClient:
    """Provider-agnostic chat client. Network calls are injectable for tests."""

    def __init__(self, provider: str, api_key: str | None = None,
                 model: str | None = None, env_file: str = "checkit.env",
                 timeout: float = 120.0, poster=None):
        self.provider = provider.lower()
        if self.provider not in PROVIDERS:
            raise ValueError(f"Unknown provider {self.provider!r}")
        self.api_key = resolve_api_key(self.provider, api_key, env_file)
        self.model = model or DEFAULT_MODELS[self.provider]
        self.timeout = timeout
        self._poster = poster or self._post

    def _headers(self) -> dict:
        if self.provider == "claude":
            return {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            }
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _build_payload(self, system: str, user: str) -> dict:
        if self.provider == "claude":
            return {
                "model": self.model,
                "max_tokens": 8192,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            }
        return {
            "model": self.model,
            "max_tokens": 8192,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }

    def _post(self, url: str, headers: dict, payload: dict) -> dict:
        resp = requests.post(url, headers=headers, json=payload,
                             timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _extract_text(provider: str, data: dict) -> str:
        if provider == "claude":
            parts = data.get("content", [])
            return "".join(p.get("text", "") for p in parts
                           if isinstance(p, dict) and p.get("type") == "text")
        choices = data.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "") or ""
        return ""

    def complete(self, system: str, user: str) -> LLMResponse:
        payload = self._build_payload(system, user)
        data = self._poster(ENDPOINTS[self.provider], self._headers(), payload)
        return LLMResponse(
            provider=self.provider,
            model=self.model,
            text=self._extract_text(self.provider, data),
            raw=data,
        )
