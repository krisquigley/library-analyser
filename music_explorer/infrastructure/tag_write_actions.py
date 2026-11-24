"""Previewed tag-write actions, kept in memory for the Explorer's lifetime (#132).

Tokens are unguessable. Only the most recent actions are kept, so an old preview simply has to be made again.
"""
from collections import OrderedDict
import secrets
import threading

from music_explorer.application.ports.tag_write_actions import TagWriteAction

DEFAULT_CAPACITY = 32


class InMemoryTagWriteActions:
    def __init__(self, capacity: int = DEFAULT_CAPACITY):
        self._capacity = capacity
        self._actions: OrderedDict[str, TagWriteAction] = OrderedDict()
        self._lock = threading.Lock()

    def new_token(self) -> str:
        return secrets.token_urlsafe(32)

    def save(self, action: TagWriteAction) -> None:
        with self._lock:
            self._actions[action.token] = action
            self._actions.move_to_end(action.token)
            while len(self._actions) > self._capacity:
                self._actions.popitem(last=False)

    def find(self, token: str) -> TagWriteAction | None:
        with self._lock:
            return self._actions.get(token)
