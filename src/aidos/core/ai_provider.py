"""AI провайдер протоколы — Strategy паттерн."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class AIProvider(Protocol):
    def chat_with_default_system(self, messages: list[dict]) -> str: ...
    def is_available(self) -> bool: ...
