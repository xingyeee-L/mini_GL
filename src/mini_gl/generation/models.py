"""Replaceable local chat-model boundary."""

from __future__ import annotations

from typing import Protocol


class ChatModel(Protocol):
    name: str

    def generate(self, *, system_prompt: str, user_prompt: str) -> str: ...
