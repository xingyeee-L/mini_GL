"""Strict loopback client for an OpenAI-compatible local inference server."""

from __future__ import annotations

import http.client
import json
from urllib.parse import urlparse

from mini_gl.generation.models import ChatResponse


class LocalModelError(RuntimeError):
    """Base error with a privacy-safe message for local inference failures."""


class LocalModelTimeoutError(LocalModelError):
    """Raised when the local inference service exceeds its configured deadline."""


class LocalModelUnavailableError(LocalModelError):
    """Raised when the configured loopback inference service cannot be reached."""


class LocalOpenAIChatModel:
    def __init__(self, endpoint: str, model: str, *, timeout_seconds: float = 120.0) -> None:
        parsed = urlparse(endpoint)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Local model endpoint must use HTTP on a loopback host")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Local model endpoint contains unsupported URL components")
        if not model.strip():
            raise ValueError("Local model name is required")
        self.host = parsed.hostname
        self.port = parsed.port or 80
        self.path = parsed.path or "/v1/chat/completions"
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.name = f"local-openai:{model}"

    def generate(self, *, system_prompt: str, user_prompt: str) -> ChatResponse:
        payload = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0,
                "stream": False,
            },
            ensure_ascii=False,
        ).encode()
        connection = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout_seconds)
        try:
            connection.request(
                "POST",
                self.path,
                body=payload,
                headers={"Content-Type": "application/json", "Content-Length": str(len(payload))},
            )
            response = connection.getresponse()
            raw = response.read(1_048_577)
        except TimeoutError as exc:
            raise LocalModelTimeoutError(
                "Local model timed out; verify the model is loaded and retry"
            ) from exc
        except OSError as exc:
            raise LocalModelUnavailableError(
                "Local model is unavailable; start the configured loopback service and retry"
            ) from exc
        finally:
            connection.close()
        if len(raw) > 1_048_576:
            raise RuntimeError("Local model response exceeded the safety limit")
        if response.status != 200:
            raise RuntimeError(f"Local model returned HTTP {response.status}")
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise LocalModelError("Local model returned an invalid JSON response") from exc
        try:
            answer = value["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Local model returned an invalid response") from exc
        if not isinstance(answer, str) or not answer.strip():
            raise RuntimeError("Local model returned an empty answer")
        usage = value.get("usage", {})
        return ChatResponse(
            answer.strip(),
            _optional_int(usage.get("prompt_tokens")),
            _optional_int(usage.get("completion_tokens")),
        )


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and value >= 0 else None
