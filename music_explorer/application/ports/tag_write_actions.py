"""Previewed tag-write actions, each behind a single-use approval token (#132).

The store keeps every action with its lifecycle state, so a token that was applied or rejected can never
approve anything again.
"""
from dataclasses import dataclass
from typing import Protocol

from music_explorer.domain.tag_change_set import TagChange


@dataclass(frozen=True)
class TagWriteAction:
    token: str
    state: str
    track_ids: tuple[str, ...]
    policy: str
    minimum_key_strength: float
    changes: tuple[TagChange, ...]
    identities: tuple[tuple[str, str], ...]


class TagWriteActions(Protocol):
    def new_token(self) -> str: ...

    def save(self, action: TagWriteAction) -> None: ...

    def find(self, token: str) -> TagWriteAction | None: ...
