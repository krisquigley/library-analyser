from collections.abc import Sequence

from music_analyzer.application.dto.models import ModelError, ModelReport, ModelResult
from music_analyzer.application.ports.models import ModelStorage


class VerifyModels:
    def __init__(self, storage: ModelStorage, model_ids: Sequence[str]):
        self._storage = storage
        self._model_ids = tuple(model_ids)

    def _perform(self, model_id: str) -> ModelResult:
        return self._storage.verify(model_id)

    def execute(self) -> ModelReport:
        results = []
        for model_id in self._model_ids:
            try:
                results.append(self._perform(model_id))
            except ModelError as error:
                results.append(ModelResult(model_id, False, 'unverified', str(error)))
        return ModelReport(tuple(results))


class DownloadModels(VerifyModels):
    def _perform(self, model_id: str) -> ModelResult:
        return self._storage.install(model_id)
