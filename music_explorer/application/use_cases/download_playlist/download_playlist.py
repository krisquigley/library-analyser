"""Download a playlist as an M3U file (#58, #121-#123, #135-#137).

The playlist walks the related-track graph from a start track, ranked by the
recipe's harmonic mixing, energy plan and mood hold. The rules live in the
domain, so a preview of the same recipe follows the same walk.
"""
from collections import defaultdict

from music_explorer.application.dto.playlists import M3UPlaylist, PlaylistRecipe
from music_explorer.domain.energy_plan import BY_DURATION, BY_TRACK_COUNT, ArcSegment, EnergyPlan, EnergyRange
from music_explorer.domain.harmonic_mixing import HarmonicMixing
from music_explorer.domain.mood_hold import MoodHold
from music_explorer.domain.percentile_rank import percentile_ranks
from music_explorer.domain.playlist_candidates import usable_energy_and_mood, walk_track
from music_explorer.domain.playlist_eligibility import BpmRange, check_start_track, eligible
from music_explorer.domain.playlist_length import goal_and_arc_lengths, shortfall_warning
from music_explorer.domain.playlist_walk import DurationGoal, walk_playlist
from music_explorer.domain.transition_ranking import transition_ranking

# The related-track edges the Explorer graph shows (its sparse_k).
GRAPH_SPARSE_K = 10


class GenerateBpmGraphM3UPlaylist:
    """Generate an M3U by walking the related-track graph from a start track."""

    def __init__(self, repository):
        self.repository = repository

    def execute(self, recipe: PlaylistRecipe):
        harmonic_mixing = HarmonicMixing(minimum_key_strength=recipe.minimum_key_strength) if recipe.harmonic_mixing else None
        start_track_id = str(recipe.start_track_id or '')
        bpm_range = BpmRange.of(recipe.bpm_min, recipe.bpm_max)
        goal, arc_lengths = goal_and_arc_lengths(recipe.energy_plan, recipe.length, recipe.duration_minutes)
        if not start_track_id:
            raise ValueError('start track is required')

        tracks = tuple(self.repository.playlist_export_tracks())
        candidates = {track.track_id: track for track in tracks if eligible(track, bpm_range)}
        if start_track_id not in candidates:
            start = next((track for track in tracks if track.track_id == start_track_id), None)
            if start is not None:
                check_start_track(start, bpm_range)
            raise ValueError('start track is not playable or available')
        walk_tracks = {track_id: walk_track(track, harmonic_mixing) for track_id, track in candidates.items()}
        if not goal.admits(walk_tracks[start_track_id]):
            raise ValueError('start track has no verified duration for a duration playlist')

        plan, hold = self._energy_plan_and_mood_hold(candidates, recipe, goal, arc_lengths)
        walk = walk_playlist(start_track_id, walk_tracks, self._related(candidates), goal,
                             rank_transition=transition_ranking(harmonic_mixing, plan, hold))
        warning = None if walk.complete else shortfall_warning(goal)
        content = '#EXTM3U\n' + ''.join(candidates[track_id].path + '\n' for track_id in walk.track_ids)
        return M3UPlaylist(content, walk.track_ids, warning)

    def _related(self, candidates):
        related = defaultdict(list)
        for edge in self._related_track_edges():
            if edge.a in candidates and edge.b in candidates:
                related[edge.a].append((edge.b, float(edge.score)))
                related[edge.b].append((edge.a, float(edge.score)))
        return related

    def _energy_plan_and_mood_hold(self, candidates, recipe, goal, arc_lengths):
        mood_hold = recipe.mood_hold
        if not recipe.energy_plan and not mood_hold:
            return None, None
        segments = tuple(ArcSegment(arc.shape, length, EnergyRange.of(low=arc.energy_low, high=arc.energy_high))
                         for arc, length in zip(recipe.energy_plan, arc_lengths))
        evidence = self.repository.playlist_mood_evidence(mood_hold or None)
        arousal, mood = usable_energy_and_mood(candidates, evidence)
        if mood_hold and not mood:
            raise ValueError(f"No eligible track has a score for the mood '{mood_hold}'")
        timeline = BY_DURATION if isinstance(goal, DurationGoal) else BY_TRACK_COUNT
        plan = EnergyPlan(segments, percentile_ranks(arousal), timeline) if segments else None
        hold = MoodHold(percentile_ranks(mood)) if mood_hold else None
        return plan, hold

    def _related_track_edges(self):
        # Only a ready graph build is current; a stale one would walk old relations.
        status, edges = self.repository.related_track_edges(GRAPH_SPARSE_K)
        return edges if status is not None and status.get('state') == 'ready' else ()


GenerateBpmGraphM3U = GenerateBpmGraphM3UPlaylist
