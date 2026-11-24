"""Preview a tag-write action (#132): exactly which files and fields would change, old -> new.

Nothing is written. When there is something to change, the action is stored as previewed behind a new
single-use token, which the listener's approval must present to apply it.
"""
from dataclasses import dataclass
import math

from music_explorer.application.ports.event_bus import EventBus
from music_explorer.application.ports.tag_write_actions import TagWriteAction, TagWriteActions
from music_explorer.application.ports.taggable_tracks import TaggableTracks
from music_explorer.application.ports.track_tags import TrackTags
from music_explorer.application.tag_change_planning import plan_tag_write
from music_explorer.domain.harmonic_mixing import DEFAULT_MINIMUM_KEY_STRENGTH
from music_explorer.domain.tag_change_set import EXISTING_TAG_POLICIES, FILL_EMPTY, TagChange

MAXIMUM_TRACKS_PER_ACTION = 100


class TagWriteRequestError(ValueError):
    pass


@dataclass(frozen=True)
class PreviewTagWriteRequest:
    track_ids: tuple[str, ...]
    policy: str = FILL_EMPTY
    minimum_key_strength: float = DEFAULT_MINIMUM_KEY_STRENGTH


@dataclass(frozen=True)
class TagWritePreview:
    token: str | None
    changes: tuple[TagChange, ...]
    skipped: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class TagWritePreviewed:
    token: str | None
    change_count: int
    skipped_count: int


class PreviewTagWrite:
    def __init__(self, tracks: TaggableTracks, track_tags: TrackTags, actions: TagWriteActions, events: EventBus):
        self._tracks = tracks
        self._track_tags = track_tags
        self._actions = actions
        self._events = events

    def execute(self, request: PreviewTagWriteRequest) -> TagWritePreview:
        _check(request)
        plan = plan_tag_write(request.track_ids, policy=request.policy,
                              minimum_key_strength=request.minimum_key_strength, tracks=self._tracks,
                              track_tags=self._track_tags)
        token = self._actions.new_token() if plan.changes else None
        if token:
            self._actions.save(TagWriteAction(token, 'previewed', request.track_ids, request.policy,
                                              request.minimum_key_strength, plan.changes, plan.identities))
        self._events.publish(TagWritePreviewed(token, len(plan.changes), len(plan.skipped)))
        return TagWritePreview(token, plan.changes, plan.skipped)


def _check(request):
    if not request.track_ids:
        raise TagWriteRequestError('Choose at least one track to tag')
    if len(request.track_ids) > MAXIMUM_TRACKS_PER_ACTION:
        raise TagWriteRequestError(f'Tag at most {MAXIMUM_TRACKS_PER_ACTION} tracks in one action')
    if len(set(request.track_ids)) != len(request.track_ids):
        raise TagWriteRequestError('A track is chosen more than once')
    if request.policy not in EXISTING_TAG_POLICIES:
        raise TagWriteRequestError('Choose fill-empty or replace-existing for tags that already have a value')
    strength = request.minimum_key_strength
    if isinstance(strength, bool) or not isinstance(strength, (int, float)) or not math.isfinite(strength) \
            or not 0 <= strength <= 1:
        raise TagWriteRequestError('The minimum key strength must be between 0 and 1')
