"""Model setup results; integrity is not inference validation."""
from dataclasses import dataclass


class ModelError(Exception):
    """Actionable model setup failure at a port boundary."""


@dataclass(frozen=True)
class ModelResult:
    model_id: str
    available: bool
    integrity: str
    detail: str


@dataclass(frozen=True)
class ModelReport:
    models: tuple[ModelResult, ...]
    inference_validated: bool = False

    @property
    def ready(self) -> bool:
        return bool(self.models) and all(model.available for model in self.models)
