from typing import ContextManager, Protocol
from music_analyzer.application.dto.analysis import AudioSource, DecodedAudio, StageResult


class AudioDecoder(Protocol):
    def decode(self, source: AudioSource, max_duration: float) -> ContextManager[DecodedAudio]:
        """Own/release bounded temporary audio; reject rather than truncate."""
        ...


class AnalysisEngine(Protocol):
    def analyze(self, stage: str, audio: DecodedAudio) -> StageResult:
        """Return mapped native scores and provenance; raise AnalysisError on failure."""
        ...


class AnalysisRepository(Protocol):
    def start(self, source: AudioSource) -> str: ...
    def save_stage(self, run_id: str, result: StageResult) -> None: ...
    def finish(self, run_id: str, status: str, detail: str) -> None: ...
