"""How the playlist walk ranks a transition (#121, #122, #123, #137).

By default a transition ranks by its relation score. Harmonic mixing, an energy
plan and a mood hold each adjust it; none of them excludes a track.
"""
from music_explorer.domain.playlist_walk import by_relation_score


def transition_ranking(harmonic_mixing, plan, hold):
    if harmonic_mixing is None and plan is None and hold is None:
        return by_relation_score
    planned = _PlannedTargets(plan)

    def rank(walk, to_track, relation_score, position):
        score = relation_score
        if harmonic_mixing is not None:
            previous = walk[-1]
            score = harmonic_mixing.transition_score(score, previous.key, to_track.key, previous.bpm, to_track.bpm)
        if plan is not None:
            score += plan.miss(to_track.track_id, planned.after(walk))
        if hold is not None:
            score += hold.adjustment(to_track.track_id)
        return score
    return rank


class _PlannedTargets:
    """The plan's target for the next track, worked out once for each walk the search ranks candidates after."""

    def __init__(self, plan):
        self.plan = plan
        self.walk = None
        self.target = None

    def after(self, walk):
        if walk is not self.walk:
            self.walk, self.target = walk, self.plan.target_after(walk)
        return self.target
