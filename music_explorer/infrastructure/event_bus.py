"""An in-process event bus: each published event goes to its type's subscribers, in subscription order."""
from collections import defaultdict


class InProcessEventBus:
    def __init__(self):
        self._handlers = defaultdict(list)

    def subscribe(self, event_type: type, handler) -> None:
        self._handlers[event_type].append(handler)

    def publish(self, event: object) -> None:
        for handler in tuple(self._handlers[type(event)]):
            handler(event)
