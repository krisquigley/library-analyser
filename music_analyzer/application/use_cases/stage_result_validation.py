"""Pure retained stage checkpoint policy, independent of serialization and storage."""
from math import isclose

from music_analyzer.application.dto.analysis import StageResult
from music_analyzer.domain.analysis import ScoreWindow, finite, summarize_scores


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
    raw = result.raw_predictions
    if (not isinstance(raw, (list, tuple))
            or any(not isinstance(section, (list, tuple))
                   or any(not isinstance(row, (list, tuple)) or not all(finite(score) for score in row)
                          for row in section)
                   for section in raw)):
        raise ValueError('Invalid raw scores')
    if (not isinstance(result.windows, (list, tuple))
            or any(not isinstance(window, ScoreWindow)
                   or not finite(window.start) or not finite(window.end)
                   or not isinstance(window.scores, (list, tuple))
                   for window in result.windows)):
        raise ValueError('Invalid score shape, score, or coverage window')
    summary = result.summary
    if summary is None:
        if result.windows:
            raise ValueError('Windows require summary labels')
        return
    if (not summary.labels
            or any(not isinstance(label, str) for label in summary.labels)
            or any(len(vector) != len(summary.labels) or not all(finite(value) for value in vector)
                   for vector in (summary.mean, summary.minimum, summary.maximum))
            or not finite(summary.coverage) or not 0 < summary.coverage <= 1):
        raise ValueError('Invalid stage summary')
    if result.windows:
        duration = sum(window.end - window.start for window in result.windows) / summary.coverage
        # Inverting rounded coverage can lose an ULP at the final boundary.
        # Correct reconstruction roundoff only, as retained readers do.
        end = result.windows[-1].end
        if finite(end) and duration < end and isclose(duration, end, rel_tol=1e-14, abs_tol=0):
            duration = end
        summarize_scores(summary.labels, result.windows, duration)
