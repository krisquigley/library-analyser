"""Pure retained stage checkpoint policy, independent of serialization and storage."""
from music_analyzer.application.dto.analysis import StageResult
from music_analyzer.domain.analysis import finite


def validate_stage_result(result: StageResult) -> None:
    """Check retained summary shape without imposing graph-feature semantics.

    Checkpoints may contain string-valued estimates or omit optional summaries.
    Compact graph evidence has a separate, stricter contract at publication.
    """
    summary = result.summary
    if summary is None:
        return
    if (not summary.labels
            or any(not isinstance(label, str) for label in summary.labels)
            or any(len(vector) != len(summary.labels) or not all(finite(value) for value in vector)
                   for vector in (summary.mean, summary.minimum, summary.maximum))
            or not finite(summary.coverage) or not 0 < summary.coverage <= 1):
        raise ValueError('Invalid stage summary')
