from music_analyzer.application.dto.analysis import AnalysisError, AnalysisReport, AudioSource
from music_analyzer.application.ports.analysis import AudioDecoder, AnalysisEngine, AnalysisRepository
from music_analyzer.domain.analysis import finite


class AnalyzeTrack:
    """One explicit run; checkpoint each stage, never claim partial success.

    Embedding reuse is supplied by the engine; this use case always checkpoints
    a new full run. It makes no acoustic recording identity assumptions.
    Unexpected programmer/storage exceptions propagate, not hidden as success.
    """
    def __init__(self, decoder: AudioDecoder, engine: AnalysisEngine, repository: AnalysisRepository):
        self._decoder, self._engine, self._repository = decoder, engine, repository

    def execute(self, source: AudioSource, max_duration: float = 900) -> AnalysisReport:
        if not finite(max_duration) or not 0 < max_duration <= 3600:
            raise ValueError('Maximum duration must be positive and at most 3600 seconds')
        run_id = self._repository.start(source)
        results = []
        current = 'decode'
        try:
            with self._decoder.decode(source, max_duration) as audio:
                for current in ('bpm', 'key', 'genres', 'mood', 'instruments', 'energy'):
                    result = self._engine.analyze(current, audio)
                    if result.stage != current:
                        raise AnalysisError('Engine returned a different stage')
                    self._repository.save_stage(run_id, result)
                    results.append(result)
        except AnalysisError as error:
            detail = f'{current}: {error}'
            self._repository.finish(run_id, 'failed', detail)
            return AnalysisReport(run_id, 'failed', tuple(results), detail)
        except KeyboardInterrupt:
            self._repository.finish(run_id, 'interrupted', f'{current}: interrupted')
            raise
        self._repository.finish(run_id, 'completed', '')
        return AnalysisReport(run_id, 'completed', tuple(results))
