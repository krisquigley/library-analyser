"""Explicit external representation mapping; never deserialize arbitrary objects."""
from music_analyzer.application.dto.analysis import StageResult
from music_analyzer.domain.analysis import ScoreSummary, ScoreWindow, finite, summarize_scores


def stage_from_mapping(data):
    summary = data.get('summary')
    mapped = None
    if summary is not None:
        mapped = ScoreSummary(tuple(summary['labels']), tuple(summary['mean']),
            tuple(summary['minimum']), tuple(summary['maximum']), summary['coverage'],
            summary.get('provisional', True), summary.get('uncertainty', 'Legacy uncertainty unavailable'))
        if (not mapped.labels or any(not isinstance(x, str) for x in mapped.labels)
                or any(len(v) != len(mapped.labels) or not all(finite(x) for x in v)
                       for v in (mapped.mean, mapped.minimum, mapped.maximum))
                or not finite(mapped.coverage) or not 0 < mapped.coverage <= 1):
            raise ValueError('Invalid summary')
    for name in ('provenance', 'values'):
        pairs = data.get(name, ())
        if not isinstance(pairs, (list, tuple)):
            raise ValueError('Invalid ' + name)
        for pair in pairs:
            if (not isinstance(pair, (list, tuple)) or len(pair) != 2 or not isinstance(pair[0], str)
                    or not (isinstance(pair[1], str) or (name == 'values' and finite(pair[1])))):
                raise ValueError('Invalid ' + name)
    windows = tuple(ScoreWindow(w['start'], w['end'], tuple(w['scores'])) for w in data.get('windows', ()))
    if windows:
        if mapped is None: raise ValueError('Windows require summary labels')
        duration = sum(w.end-w.start for w in windows) / mapped.coverage
        summarize_scores(mapped.labels, windows, duration)
    raw = tuple(tuple(tuple(row) for row in section) for section in data.get('raw_predictions', ()))
    if any(not finite(x) for section in raw for row in section for x in row):
        raise ValueError('Invalid raw scores')
    if not isinstance(data['stage'], str) or not isinstance(data['uncertainty'], str):
        raise ValueError('Invalid stage text')
    return StageResult(data['stage'], tuple(tuple(p) for p in data['provenance']), data['uncertainty'],
                       tuple(tuple(p) for p in data.get('values', ())), windows, mapped, raw)


