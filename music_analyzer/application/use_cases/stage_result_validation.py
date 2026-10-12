"""Pure retained stage checkpoint policy, independent of serialization and storage."""
from music_analyzer.application.dto.analysis import StageResult
from music_analyzer.domain.analysis import finite


def validate_stage_result(result: StageResult) -> None:
    """Check retained text and summary shape without graph-feature semantics.

    Checkpoints may contain string-valued estimates or omit optional summaries.
    Compact graph evidence has a separate, stricter contract at publication.
    """
    if not isinstance(result.stage, str) or not isinstance(result.uncertainty, str):
        raise ValueError('Invalid stage text')
    if (not isinstance(result.provenance, (list, tuple))
            or any(not isinstance(pair, (list, tuple)) or len(pair) != 2
                   or not all(isinstance(value, str) for value in pair)
                   for pair in result.provenance)):
        raise ValueError('Invalid stage provenance')
    if (not isinstance(result.values, (list, tuple))
            or any(not isinstance(pair, (list, tuple)) or len(pair) != 2
                   or not isinstance(pair[0], str)
                   or isinstance(pair[1], bool)
                   or not (isinstance(pair[1], str) or finite(pair[1]))
                   for pair in result.values)):
        raise ValueError('Invalid stage values')
    summary = result.summary
    if summary is None:
        return
    if (not summary.labels
            or any(not isinstance(label, str) for label in summary.labels)
            or any(len(vector) != len(summary.labels) or not all(finite(value) for value in vector)
                   for vector in (summary.mean, summary.minimum, summary.maximum))
            or not finite(summary.coverage) or not 0 < summary.coverage <= 1):
        raise ValueError('Invalid stage summary')
