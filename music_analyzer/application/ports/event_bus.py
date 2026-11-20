"""Use cases announce what they did as events; whoever cares subscribes (AGENTS.md)."""
from typing import Protocol


class EventBus(Protocol):
    def publish(self, event: object) -> None: ...
