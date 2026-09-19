"""Explicit export mapping over application DTOs."""
def stage_to_mapping(stage):
    summary = stage.summary
    return {'stage': stage.stage, 'provenance': dict(stage.provenance), 'uncertainty': stage.uncertainty,
        'values': dict(stage.values), 'windows': [{'start': w.start, 'end': w.end, 'scores': w.scores} for w in stage.windows],
        'raw_predictions': stage.raw_predictions,
        'summary': None if summary is None else {'labels': summary.labels, 'mean': summary.mean,
            'minimum': summary.minimum, 'maximum': summary.maximum, 'coverage': summary.coverage,
            'provisional': summary.provisional, 'uncertainty': summary.uncertainty}}


def review_to_mapping(report):
    track, run = report.track, report.track.run
    return {'track_id': track.track_id, 'sha256': track.sha256, 'size': track.size,
        'locations': track.locations, 'overrides': dict(track.overrides), 'effective': dict(report.effective),
        'threshold': report.threshold, 'selections': dict(report.selections),
        'needs_review': report.needs_review, 'reasons': report.reasons,
        'run': None if run is None else {'run_id': run.run_id, 'status': run.status, 'detail': run.detail,
            'stages': [stage_to_mapping(s) for s in run.stages]}}
