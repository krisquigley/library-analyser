"""Preview a playlist before downloading it (#138).

The walk follows the domain's generation rule, so the preview lists the same
tracks as the M3U download of the same recipe. Arousal is always read, so every
preview can show the energy actually placed, in the graph's numbers (#265).
"""
from music_explorer.application.dto.playlists import PlaylistRecipe
from music_explorer.application.dto.playlist_preview import PlaylistPreview, PreviewTrack, PreviewTransition
from music_explorer.domain.harmonic_mixing import HarmonicMixing, MusicalKey, camelot_code
from music_explorer.domain.playlist_candidates import usable_energy_and_mood
from music_explorer.domain.playlist_generation import PlaylistRules, generate_walk
from music_explorer.domain.playlist_steps import playlist_step

# The related-track edges the Explorer graph shows (its sparse_k).
GRAPH_SPARSE_K = 10


class PreviewPlaylist:
    def __init__(self, repository):
        self.repository = repository

    def execute(self, recipe: PlaylistRecipe) -> PlaylistPreview:
        rules = PlaylistRules.of(
            start_track_id=recipe.start_track_id, bpm_min=recipe.bpm_min, bpm_max=recipe.bpm_max, length=recipe.length,
            duration_minutes=recipe.duration_minutes, harmonic_mixing=recipe.harmonic_mixing,
            minimum_key_strength=recipe.minimum_key_strength, energy_plan=recipe.energy_plan, mood_hold=recipe.mood_hold)
        tracks = tuple(self.repository.playlist_export_tracks())
        evidence = self.repository.playlist_mood_evidence(rules.mood_hold)
        generated = generate_walk(rules, tracks, self._related_track_edges(), evidence)
        arousal, _mood = usable_energy_and_mood(generated.candidates, evidence)
        walk = tuple(generated.walk_tracks[track_id] for track_id in generated.track_ids)
        targets = generated.plan.targets_along(walk) if generated.plan else (None,) * len(walk)
        placed = tuple(_preview_track(generated.candidates[track.track_id], arousal, target)
                       for track, target in zip(walk, targets))
        mixing = rules.harmonic_mixing or HarmonicMixing()
        transitions = tuple(_transition(before, after, mixing) for before, after in zip(walk, walk[1:]))
        return PlaylistPreview(placed, transitions, generated.complete, generated.warning)

    def _related_track_edges(self):
        # Only a ready graph build is current; a stale one would walk old relations.
        status, edges = self.repository.related_track_edges(GRAPH_SPARSE_K)
        return edges if status is not None and status.get('state') == 'ready' else ()


def _preview_track(track, arousal, target):
    key = MusicalKey.parse(getattr(track, 'key', None), getattr(track, 'scale', None))
    return PreviewTrack(
        track_id=track.track_id, title=getattr(track, 'title', '') or '', artist=getattr(track, 'artist', '') or '',
        bpm=track.bpm, key=f'{track.key} {key.scale}' if key else None, camelot=camelot_code(key) if key else None,
        arousal=arousal.get(track.track_id), energy_target=target,
        duration_seconds=getattr(track, 'duration_seconds', None))


def _transition(before, after, mixing):
    step = playlist_step(before, after, mixing)
    return PreviewTransition(from_track_id=before.track_id, to_track_id=after.track_id, key_compatible=step.key_compatible,
                             bpm_step_smooth=step.bpm_step_smooth, bpm_change=step.bpm_change)
