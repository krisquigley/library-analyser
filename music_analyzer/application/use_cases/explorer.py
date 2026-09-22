from music_analyzer.application.dto.explorer import (
    AutomaticEvidence,
    ExplorerFieldEvidence,
    ExplorerMetadata,
    ExplorerSnapshot,
    ExplorerTrackDetail,
)
from music_analyzer.application.ports.explorer import ExplorerRepository
from music_analyzer.domain.review import FIELDS


class ListExplorerTracks:
    def __init__(self, repository: ExplorerRepository):
        self.repository = repository

    def execute(self, limit=100, after=None):
        if limit == 'all':
            metadata, tracks = self.repository.candidate_snapshot()
            return ExplorerSnapshot(self._metadata(metadata, len(tracks)), tuple(_map_track(track) for track in tracks))
        if not isinstance(limit, int) or limit < 1 or limit > 500:
            raise ValueError('Explorer list limit must be between 1 and 500 or all')
        metadata, track_count, tracks = self.repository.list_tracks(limit, after)
        return ExplorerSnapshot(self._metadata(metadata, track_count), tuple(_map_track(track) for track in tracks))

    def _metadata(self, raw, track_count):
        return ExplorerMetadata(
            application_id=int(raw.get('application_id', 0)),
            schema_version=int(raw.get('schema_version', 0)),
            read_policy=str(raw.get('read_policy', 'bounded_read_transaction')),
            track_count=track_count,
        )


class GetExplorerTrackDetail:
    def __init__(self, repository: ExplorerRepository):
        self.repository = repository

    def execute(self, handle):
        if handle not in self.repository.track_ids():
            raise ValueError('Unknown explorer track')
        return _map_track(self.repository.read_track(handle))


class ExploreCatalogue:
    def __init__(self, repository: ExplorerRepository):
        self.repository = repository

    def list_tracks(self):
        return ListExplorerTracks(self.repository).execute(limit='all')

    def track_detail(self, handle):
        return GetExplorerTrackDetail(self.repository).execute(handle)


def _map_track(track):
    stages = {stage.stage: stage for stage in track.run.stages} if track.run else {}
    manual = dict(track.overrides)
    reasons = []
    if not track.available_locations:
        reasons.append('No available catalogue location')
    if not track.run:
        reasons.append('No identity-linked analysis; legacy/path-only runs are not attributed')
    elif track.run.status != 'completed':
        reasons.append('Latest run: ' + track.run.status)
    fields = {}
    for field in FIELDS:
        stage = stages.get(field)
        missing_reason = ''
        automatic = AutomaticEvidence()
        if stage is None:
            missing_reason = field + ': missing result'
            reasons.append(missing_reason)
        else:
            summary_values = ()
            coverage = None
            if stage.summary is not None:
                summary_values = tuple(zip(stage.summary.labels, stage.summary.mean))
                coverage = stage.summary.coverage
            automatic = AutomaticEvidence(stage.values, summary_values, coverage, stage.provenance, stage.uncertainty)
            if stage.uncertainty:
                reasons.append(field + ': ' + stage.uncertainty)
            if stage.summary and stage.summary.provisional:
                reasons.append(field + ': provisional, uncalibrated scores')
        manual_text = manual.get(field)
        if manual_text is not None:
            effective = 'manual_text'
            typed_status = 'unresolved'
        elif automatic.values or automatic.summary_values:
            effective = 'automatic'
            typed_status = 'absent'
        else:
            effective = 'missing'
            typed_status = 'absent'
        fields[field] = ExplorerFieldEvidence(field, automatic, manual_text, effective, typed_status, missing_reason)
    return ExplorerTrackDetail(
        handle=track.track_id,
        track_id=track.track_id,
        sha256=track.sha256,
        size=track.size,
        display_label=track.display_label,
        available_locations=track.available_locations,
        latest_run_id=track.run.run_id if track.run else None,
        latest_run_status=track.run.status if track.run else None,
        latest_run_detail='',
        fields=fields,
        reasons=tuple(reasons),
    )
