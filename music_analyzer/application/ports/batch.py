"""Durable queue and exclusive dispatcher boundaries."""
from dataclasses import dataclass
from typing import ContextManager, Protocol


@dataclass(frozen=True)
class BatchJob:
    track_id: str
    fingerprint: str
    state: str
    attempts: int = 0
    run_id: str | None = None
    detail: str = ''


class BatchQueue(Protocol):
    def exclusive(self) -> ContextManager: ...
    def recover(self) -> None: ...
    def tracks(self) -> tuple[str, ...]: ...
    def get_job(self, track_id: str) -> BatchJob | None: ...
    def put_job(self, job: BatchJob) -> None: ...
    def status(self) -> tuple[BatchJob, ...]: ...
