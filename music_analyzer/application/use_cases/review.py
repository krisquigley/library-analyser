from music_analyzer.application.dto.review import ReviewReport
from music_analyzer.application.ports.review import ReviewRepository, ReviewOutput
from music_analyzer.domain.analysis import finite, select_scores
from music_analyzer.domain.review import FIELDS, validate_override, effective_value


class ReviewTracks:
    def __init__(self, repository: ReviewRepository):
        self.repository = repository

    def show(self, track_id, threshold=None):
        if threshold is not None and not finite(threshold):
            raise ValueError('Finite threshold required')
        track = self.repository.read_track(track_id)
        stages = {s.stage: s for s in track.run.stages} if track.run else {}
        reasons = []
        if not track.locations: reasons.append('No available catalogue location')
        if not track.run: reasons.append('No identity-linked analysis; legacy/path-only runs are not attributed')
        elif track.run.status != 'completed': reasons.append('Latest run: ' + track.run.status)
        selections, effective = [], []
        manual = dict(track.overrides)
        for field in FIELDS:
            stage = stages.get(field)
            automatic = None
            if stage is None:
                reasons.append(field + ': missing result')
            else:
                automatic = stage.values or None
                if stage.uncertainty: reasons.append(field + ': ' + stage.uncertainty)
                if stage.summary and stage.summary.provisional:
                    reasons.append(field + ': provisional, uncalibrated scores')
                if threshold is not None and stage.summary:
                    summary = stage.summary
                    if stage.windows and 0 < summary.coverage <= 1:
                        duration = sum(w.end-w.start for w in stage.windows) / summary.coverage
                        automatic = select_scores(summary.labels, stage.windows, duration, threshold)
                    else:
                        automatic = None
                        reasons.append(field + ': retained windows/coverage unavailable')
                    selections.append((field, automatic))
            effective.append((field, effective_value(automatic, manual.get(field))))
        return ReviewReport(track, tuple(effective), tuple(selections), threshold, bool(reasons), tuple(reasons))

    def list(self, needs_review=False):
        for track in self.repository.track_ids():
            report = self.show(track)
            if not needs_review or report.needs_review:
                yield report

    def override(self, track_id, field, value):
        validate_override(field, value)
        self.repository.set_override(track_id, field, value)
        return self.show(track_id)

    def export(self, output: ReviewOutput, format, destination):
        if format not in ('json', 'csv'): raise ValueError('Export format must be json or csv')
        output.write(self.list(), format, destination)
