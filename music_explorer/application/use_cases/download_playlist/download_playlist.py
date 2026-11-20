"""Download a playlist as an M3U file (#58, #121-#123, #135-#137).

The walk follows the domain's generation rule, so a preview of the same recipe
lists the same tracks (#138).
"""
from music_explorer.application.dto.playlists import M3UPlaylist, PlaylistRecipe
from music_explorer.domain.playlist_generation import PlaylistRules, generate_walk

# The related-track edges the Explorer graph shows (its sparse_k).
GRAPH_SPARSE_K = 10


class GenerateBpmGraphM3UPlaylist:
    """Generate an M3U by walking the related-track graph from a start track."""

    def __init__(self, repository):
        self.repository = repository

    def execute(self, recipe: PlaylistRecipe):
        rules = PlaylistRules.of(
            start_track_id=recipe.start_track_id, bpm_min=recipe.bpm_min, bpm_max=recipe.bpm_max, length=recipe.length,
            duration_minutes=recipe.duration_minutes, harmonic_mixing=recipe.harmonic_mixing,
            minimum_key_strength=recipe.minimum_key_strength, energy_plan=recipe.energy_plan, mood_hold=recipe.mood_hold)
        tracks = tuple(self.repository.playlist_export_tracks())
        evidence = self.repository.playlist_mood_evidence(rules.mood_hold) if rules.needs_evidence else {}
        generated = generate_walk(rules, tracks, self._related_track_edges(), evidence)
        content = '#EXTM3U\n' + ''.join(generated.candidates[track_id].path + '\n' for track_id in generated.track_ids)
        return M3UPlaylist(content, generated.track_ids, generated.warning)

    def _related_track_edges(self):
        # Only a ready graph build is current; a stale one would walk old relations.
        status, edges = self.repository.related_track_edges(GRAPH_SPARSE_K)
        return edges if status is not None and status.get('state') == 'ready' else ()


GenerateBpmGraphM3U = GenerateBpmGraphM3UPlaylist
