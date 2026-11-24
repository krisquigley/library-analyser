"""Apply an approved tag-write action (#132): write exactly what was previewed, once, and report each file.

The approval token is spent whatever happens. The action is planned again first; if any tag or analysis
value moved since the preview, nothing is written and the action is rejected. A file whose identity no
longer matches its analysis is skipped. Every file's outcome is reported: written, skipped or failed.
"""
from dataclasses import dataclass, replace

from music_explorer.application.ports.event_bus import EventBus
from music_explorer.application.ports.file_identity import FileIdentity
from music_explorer.application.ports.tag_write_actions import TagWriteActions
from music_explorer.application.ports.taggable_tracks import TaggableTracks
from music_explorer.application.ports.track_tags import OwnedTags, TrackTags, TrackTagsError
from music_explorer.application.tag_change_planning import plan_tag_write
from music_explorer.domain.tag_write_action import TagWriteActionTransitionError, next_tag_write_action_state

RESCAN_NOTICE = ('Writing tags changes the files, so the analysis no longer matches them: rescan them with '
                 'music-analyzer scan before analysing or exporting them again.')
_STALE = 'changed since the preview'


class TagWriteApprovalError(ValueError):
    pass


@dataclass(frozen=True)
class TagWriteOutcome:
    location: str
    status: str
    detail: str


@dataclass(frozen=True)
class TagWriteReport:
    outcomes: tuple[TagWriteOutcome, ...]
    notice: str


@dataclass(frozen=True)
class TagWriteApplied:
    token: str
    written: int
    skipped: int
    failed: int


@dataclass(frozen=True)
class TagWriteRejected:
    token: str
    reason: str


class ApplyTagWrite:
    def __init__(self, tracks: TaggableTracks, track_tags: TrackTags, identity: FileIdentity,
                 actions: TagWriteActions, events: EventBus):
        self._tracks = tracks
        self._track_tags = track_tags
        self._identity = identity
        self._actions = actions
        self._events = events

    def execute(self, token) -> TagWriteReport:
        action = self._approved(token)
        plan = plan_tag_write(action.track_ids, policy=action.policy,
                              minimum_key_strength=action.minimum_key_strength, tracks=self._tracks,
                              track_tags=self._track_tags)
        if (plan.changes, plan.identities) != (action.changes, action.identities):
            self._end(action, 'reject')
            self._events.publish(TagWriteRejected(action.token, _STALE))
            raise TagWriteApprovalError(f'The tags or the analysis {_STALE}: preview again')
        outcomes = tuple(self._write(location, sha256, action.changes) for location, sha256 in action.identities)
        self._end(action, 'apply')
        counts = [sum(outcome.status == status for outcome in outcomes) for status in ('written', 'skipped', 'failed')]
        self._events.publish(TagWriteApplied(action.token, *counts))
        return TagWriteReport(outcomes, RESCAN_NOTICE if counts[0] else '')

    def _approved(self, token):
        action = self._actions.find(token) if isinstance(token, str) and token else None
        if action is None:
            raise TagWriteApprovalError('This approval is unknown: preview again')
        try:
            state = next_tag_write_action_state(action.state, 'approve')
        except TagWriteActionTransitionError:
            raise TagWriteApprovalError('This approval has already been used: preview again') from None
        approved = replace(action, state=state)
        self._actions.save(approved)
        return approved

    def _end(self, action, transition):
        self._actions.save(replace(action, state=next_tag_write_action_state(action.state, transition)))

    def _write(self, location, sha256, changes):
        if self._identity.sha256(location) != sha256:
            return TagWriteOutcome(location, 'skipped',
                                   'The file changed since it was analysed: rescan it, then preview again')
        values = {change.field: change.proposed for change in changes if change.location == location}
        try:
            self._track_tags.write_owned(location, OwnedTags(values.get('bpm'), values.get('key')))
        except TrackTagsError as error:
            return TagWriteOutcome(location, 'failed', str(error))
        return TagWriteOutcome(location, 'written', _written(values))


def _written(values):
    names = {'bpm': 'BPM', 'key': 'key'}
    return ', '.join(f'{names[field]} {value}' for field, value in values.items())
