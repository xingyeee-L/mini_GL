"""Replaceable local chat-model boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ChatResponse:
    text: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class ChatModel(Protocol):
    name: str

    def generate(self, *, system_prompt: str, user_prompt: str) -> ChatResponse: ...
