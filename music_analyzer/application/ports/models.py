from typing import Protocol

from music_analyzer.application.dto.models import ModelResult


class ModelStorage(Protocol):
    def verify(self, model_id: str) -> ModelResult: ...
    def install(self, model_id: str) -> ModelResult: ...


class ModelTransfer(Protocol):
    def download(self, url: str, destination: str, expected_size: int) -> None: ...
