"""OpenAI / Azure OpenAI providers using stdlib HTTP only.

Credentials are read from environment variables and never logged.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from ..errors import AIError
from .base import AIProvider
from .json_extract import extract_json_object


def _post_json(url: str, headers: dict[str, str], payload: dict, timeout: int) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Body may echo request content; surface only status and reason.
        raise AIError(
            f"AI endpoint returned HTTP {exc.code}", detail=str(exc.reason)
        ) from exc
    except urllib.error.URLError as exc:
        raise AIError("Could not reach the AI endpoint", detail=str(exc.reason)) from exc
    except (TimeoutError, json.JSONDecodeError) as exc:
        raise AIError("AI request failed", detail=str(exc)) from exc


def _extract_message(response: dict) -> dict[str, Any]:
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AIError("AI response had an unexpected shape", detail=str(exc)) from exc
    return extract_json_object(content)


class AzureOpenAIProvider(AIProvider):
    name = "azure_openai"

    def __init__(self, timeout_seconds: int = 30) -> None:
        self.endpoint = (os.environ.get("AZURE_OPENAI_ENDPOINT") or "").rstrip("/")
        self.api_key = os.environ.get("AZURE_OPENAI_API_KEY") or ""
        self.deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT") or ""
        self.api_version = os.environ.get("AZURE_OPENAI_API_VERSION") or "2024-10-21"
        self.timeout_seconds = timeout_seconds

        missing = [
            name
            for name, value in (
                ("AZURE_OPENAI_ENDPOINT", self.endpoint),
                ("AZURE_OPENAI_API_KEY", self.api_key),
                ("AZURE_OPENAI_DEPLOYMENT", self.deployment),
            )
            if not value
        ]
        if missing:
            raise AIError(f"Azure OpenAI is not configured: missing {', '.join(missing)}")

    def analyze_raw(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        url = (
            f"{self.endpoint}/openai/deployments/{self.deployment}"
            f"/chat/completions?api-version={self.api_version}"
        )
        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        return _extract_message(
            _post_json(url, {"api-key": self.api_key}, payload, self.timeout_seconds)
        )


class OpenAIProvider(AIProvider):
    name = "openai"

    def __init__(self, timeout_seconds: int = 30) -> None:
        self.api_key = os.environ.get("OPENAI_API_KEY") or ""
        self.model = os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"
        self.base_url = (os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.timeout_seconds = timeout_seconds
        if not self.api_key:
            raise AIError("OpenAI is not configured: missing OPENAI_API_KEY")

    def analyze_raw(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        return _extract_message(
            _post_json(
                f"{self.base_url}/chat/completions",
                {"Authorization": f"Bearer {self.api_key}"},
                payload,
                self.timeout_seconds,
            )
        )
