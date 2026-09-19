"""Provisional score summaries, not probabilities or selected tags."""
from dataclasses import dataclass


def finite(value: float) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and -float('inf') < value < float('inf')


@dataclass(frozen=True)
class ScoreWindow:
    start: float
    end: float
    scores: tuple[float, ...]


@dataclass(frozen=True)
class ScoreSummary:
    labels: tuple[str, ...]
    mean: tuple[float, ...]
    minimum: tuple[float, ...]
    maximum: tuple[float, ...]
    coverage: float
    provisional: bool = True
    uncertainty: str = 'Raw scores are not calibrated; unsampled audio may differ.'


def summarize_scores(labels: tuple[str, ...], windows: tuple[ScoreWindow, ...], duration: float) -> ScoreSummary:
    """Duration-weighted mean and range over disjoint, explicitly covered windows.

    No thresholds, inferred instrument presence or arousal scale are asserted.
    Callers must supply actual coverage, not padded model-frame duration.
    """
    if not finite(duration) or duration <= 0 or not labels or not windows:
        raise ValueError('Positive finite duration, labels and score windows required')
    if len(set(labels)) != len(labels) or any(not isinstance(label, str) or not label for label in labels):
        raise ValueError('Labels must be unique nonempty strings')
    previous_end = 0
    for window in windows:
        if (not finite(window.start) or not finite(window.end)
                or not previous_end <= window.start < window.end <= duration
                or len(window.scores) != len(labels) or not all(finite(score) for score in window.scores)):
            raise ValueError('Invalid score shape, score, or coverage window')
        previous_end = window.end
    covered = sum(w.end - w.start for w in windows)
    return ScoreSummary(labels,
                        tuple(sum(w.scores[i] * ((w.end - w.start) / covered) for w in windows)
                              for i in range(len(labels))),
                        tuple(min(w.scores[i] for w in windows) for i in range(len(labels))),
                        tuple(max(w.scores[i] for w in windows) for i in range(len(labels))),
                        covered / duration)
