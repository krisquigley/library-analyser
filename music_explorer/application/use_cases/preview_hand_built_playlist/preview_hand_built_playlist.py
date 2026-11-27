"""Preview a playlist the listener built by hand from the graph (#287), as a recipe's preview shows one (#138).

Nothing is chosen or reordered: each named track that is still playable is shown in the listener's order, with its
energy in the graph's numbers and the step into it from the playable track before. A track no longer playable is left
out and the preview says so, so the listener can see the rest and remove it. There is no energy arc, so no target.
"""
from dataclasses import dataclass

from music_explorer.application.dto.playlist_preview import PlaylistPreview, PreviewTrack, PreviewTransition
from music_explorer.application.ports.playlist_export_tracks import PlaylistExportTracks
from music_explorer.application.ports.playlist_mood_evidence import PlaylistMoodEvidenceSource
from music_explorer.domain.hand_built_playlist import hand_built_track_ids
from music_explorer.domain.harmonic_mixing import HarmonicMixing, MusicalKey, camelot_code
from music_explorer.domain.playlist_candidates import usable_energy_and_mood, usable_valence, walk_track
from music_explorer.domain.playlist_steps import playlist_step

NO_MOOD_HELD = None


@dataclass(frozen=True)
class PreviewHandBuiltPlaylistRequest:
    track_ids: tuple[str, ...]


class PreviewHandBuiltPlaylist:
    def __init__(self, tracks: PlaylistExportTracks, evidence: PlaylistMoodEvidenceSource):
        self._tracks = tracks
        self._evidence = evidence

    def execute(self, request: PreviewHandBuiltPlaylistRequest) -> PlaylistPreview:
        track_ids = hand_built_track_ids(request.track_ids)
        playable = {track.track_id: track for track in self._tracks.playlist_export_tracks() if _playable(track)}
        kept = {track_id: playable[track_id] for track_id in track_ids if track_id in playable}
        evidence = self._evidence.playlist_mood_evidence(NO_MOOD_HELD)
        arousal, _mood = usable_energy_and_mood(kept, evidence)
        valence = usable_valence(kept, evidence)
        mixing = HarmonicMixing()
        walk = tuple(walk_track(track, mixing) for track in kept.values())
        transitions = tuple(_transition(before, after, mixing) for before, after in zip(walk, walk[1:]))
        left_out = len(track_ids) - len(kept)
        return PlaylistPreview(tuple(_preview_track(track, arousal, valence) for track in kept.values()), transitions,
                               complete=not left_out, warning=_left_out_warning(left_out))


def _playable(track):
    return track.exists and track.active and track.catalogued


def _preview_track(track, arousal, valence):
    key = MusicalKey.parse(track.key, track.scale)
    return PreviewTrack(track_id=track.track_id, title=track.title or '', artist=track.artist or '', bpm=track.bpm,
                        key=f'{track.key} {key.scale}' if key else None, camelot=camelot_code(key) if key else None,
                        arousal=arousal.get(track.track_id), energy_target=None, duration_seconds=track.duration_seconds,
                        valence=valence.get(track.track_id))


def _transition(before, after, mixing):
    step = playlist_step(before, after, mixing)
    return PreviewTransition(from_track_id=before.track_id, to_track_id=after.track_id, key_compatible=step.key_compatible,
                             bpm_step_smooth=step.bpm_step_smooth, bpm_change=step.bpm_change)


def _left_out_warning(count):
    if not count:
        return None
    if count == 1:
        return '1 of its tracks is no longer playable from the library; remove it to download it'
    return f'{count} of its tracks are no longer playable from the library; remove them to download it'
