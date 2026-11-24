"""What a tag-write action needs about one track, read from the analysis database in read-only mode (#132)."""
from music_explorer.application.ports.taggable_tracks import TaggableTrack


class ReadOnlyTaggableTracks:
    def __init__(self, repository):
        self._repository = repository

    def read(self, track_id: str) -> TaggableTrack | None:
        track = self._repository.find_track(track_id)
        if track is None:
            return None
        detected = _completed_stage_values(track.run)
        overrides = dict(track.overrides)
        return TaggableTrack(
            track_id=track.track_id,
            sha256=track.sha256,
            location=self._repository.first_available_location(track_id),
            detected_bpm=detected.get('bpm', {}).get('bpm'),
            tonic=detected.get('key', {}).get('key'),
            scale=detected.get('key', {}).get('scale'),
            key_strength=detected.get('key', {}).get('strength'),
            manual_bpm=overrides.get('bpm'),
            manual_key=overrides.get('key'),
        )


def _completed_stage_values(run):
    if run is None or run.status != 'completed':
        return {}
    return {stage.stage: dict(stage.values) for stage in run.stages if stage.stage in ('bpm', 'key')}
