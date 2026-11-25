"""One generation rule for every use of a playlist recipe (#58, #121-#123, #135-#138).

The M3U download and the preview of the same recipe must list the same tracks,
so both validate the recipe into `PlaylistRules` and walk with `generate_walk`.
The walk starts at the chosen track and follows the related-track graph through
eligible tracks, ranked by harmonic mixing, the energy plan and the mood hold.
"""
from collections import defaultdict
from dataclasses import dataclass
from typing import Mapping

from music_explorer.domain.arousal_scale import ArousalScale
from music_explorer.domain.energy_plan import BY_DURATION, BY_TRACK_COUNT, ArcSegment, EnergyPlan, EnergyRange
from music_explorer.domain.harmonic_mixing import HarmonicMixing
from music_explorer.domain.mood_hold import MoodHold
from music_explorer.domain.percentile_rank import percentile_ranks
from music_explorer.domain.playlist_candidates import usable_energy_and_mood, walk_track
from music_explorer.domain.playlist_eligibility import BpmRange, check_start_track, eligible
from music_explorer.domain.playlist_length import goal_and_arc_lengths, shortfall_warning
from music_explorer.domain.playlist_walk import DurationGoal, walk_playlist
from music_explorer.domain.transition_ranking import transition_ranking


@dataclass(frozen=True)
class PlaylistRules:
    start_track_id: str
    bpm_range: BpmRange
    goal: object
    arcs: tuple[ArcSegment, ...]
    harmonic_mixing: HarmonicMixing | None
    mood_hold: str | None

    @classmethod
    def of(cls, *, start_track_id, bpm_min, bpm_max, length, duration_minutes, harmonic_mixing, minimum_key_strength,
           energy_plan, mood_hold) -> 'PlaylistRules':
        """The rules a recipe asks for, every value checked before anything is read."""
        mixing = HarmonicMixing(minimum_key_strength=minimum_key_strength) if harmonic_mixing else None
        start = str(start_track_id or '')
        bpm_range = BpmRange.of(bpm_min, bpm_max)
        goal, arc_lengths = goal_and_arc_lengths(energy_plan, length, duration_minutes)
        if not start:
            raise ValueError('start track is required')
        arcs = tuple(ArcSegment(arc.shape, arc_length, EnergyRange.of(low=arc.energy_low, high=arc.energy_high))
                     for arc, arc_length in zip(energy_plan, arc_lengths))
        return cls(start, bpm_range, goal, arcs, mixing, mood_hold or None)

    @property
    def needs_evidence(self) -> bool:
        return bool(self.arcs) or self.mood_hold is not None


@dataclass(frozen=True)
class GeneratedPlaylist:
    track_ids: tuple[str, ...]
    complete: bool
    warning: str | None
    candidates: Mapping
    walk_tracks: Mapping
    plan: EnergyPlan | None


def generate_walk(rules: PlaylistRules, tracks, related_edges, evidence: Mapping) -> GeneratedPlaylist:
    """Walk the related tracks for `rules`; `evidence` holds each track's arousal and mood score, if read."""
    candidates = {track.track_id: track for track in tracks if eligible(track, rules.bpm_range)}
    if rules.start_track_id not in candidates:
        start = next((track for track in tracks if track.track_id == rules.start_track_id), None)
        if start is not None:
            check_start_track(start, rules.bpm_range)
        raise ValueError('start track is not playable or available')
    walk_tracks = {track_id: walk_track(track, rules.harmonic_mixing) for track_id, track in candidates.items()}
    if not rules.goal.admits(walk_tracks[rules.start_track_id]):
        raise ValueError('start track has no verified duration for a duration playlist')
    plan, hold = _energy_plan_and_mood_hold(rules, candidates, evidence)
    walk = walk_playlist(rules.start_track_id, walk_tracks, _related(candidates, related_edges), rules.goal,
                         rank_transition=transition_ranking(rules.harmonic_mixing, plan, hold))
    warning = None if walk.complete else shortfall_warning(rules.goal)
    return GeneratedPlaylist(walk.track_ids, walk.complete, warning, candidates, walk_tracks, plan)


def _energy_plan_and_mood_hold(rules, candidates, evidence):
    if not rules.needs_evidence:
        return None, None
    arousal, mood = usable_energy_and_mood(candidates, evidence)
    if rules.mood_hold and not mood:
        raise ValueError(f"No eligible track has a score for the mood '{rules.mood_hold}'")
    timeline = BY_DURATION if isinstance(rules.goal, DurationGoal) else BY_TRACK_COUNT
    plan = EnergyPlan(rules.arcs, arousal, timeline, ArousalScale.of(arousal.values())) if rules.arcs else None
    hold = MoodHold(percentile_ranks(mood)) if rules.mood_hold else None
    return plan, hold


def _related(candidates, edges):
    related = defaultdict(list)
    for edge in edges:
        if edge.a in candidates and edge.b in candidates:
            related[edge.a].append((edge.b, float(edge.score)))
            related[edge.b].append((edge.a, float(edge.score)))
    return related
