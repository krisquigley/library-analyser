"""Issue #132: previewing a tag-write action shows exactly which files and fields would change, and writes nothing."""
import unittest

from music_explorer.application.ports.track_tags import OwnedTags
from music_explorer.application.use_cases.preview_tag_write.preview_tag_write import (
    MAXIMUM_TRACKS_PER_ACTION, PreviewTagWrite, PreviewTagWriteRequest, TagWritePreviewed, TagWriteRequestError)
from music_explorer.domain.tag_change_set import FILL_EMPTY, REPLACE_EXISTING, TagChange
from tests.unit.music_explorer.application.use_cases.tag_write_fakes import (
    FakeEvents, FakeTaggableTracks, FakeTagWriteActions, FakeTrackTags, taggable)


def preview_with(*tracks, tags=None, unreadable=()):
    track_tags, actions, events = FakeTrackTags(tags, unreadable), FakeTagWriteActions(), FakeEvents()
    return PreviewTagWrite(FakeTaggableTracks(*tracks), track_tags, actions, events), track_tags, actions, events


class PreviewTagWriteTests(unittest.TestCase):
    def test_the_preview_lists_each_change_and_stores_the_action_as_previewed(self):
        use_case, track_tags, actions, events = preview_with(taggable('t1'))
        preview = use_case.execute(PreviewTagWriteRequest(('t1',)))
        self.assertEqual((TagChange('/music/t1.mp3', 'bpm', None, '124', False),
                          TagChange('/music/t1.mp3', 'key', None, 'Am', False)), preview.changes)
        self.assertEqual('token-1', preview.token)
        stored = actions.find('token-1')
        self.assertEqual(('previewed', preview.changes, (('/music/t1.mp3', 'sha-t1'),)),
                         (stored.state, stored.changes, stored.identities))
        self.assertEqual([], track_tags.writes)
        self.assertEqual([TagWritePreviewed('token-1', 2, 0)], events.published)

    def test_overrides_win_and_existing_values_are_kept_unless_replacing(self):
        track = taggable('t1', manual_bpm='128', manual_key='C major')
        tags = {'/music/t1.mp3': OwnedTags('120', None)}
        use_case, *_ = preview_with(track, tags=tags)
        self.assertEqual((TagChange('/music/t1.mp3', 'key', None, 'C', False),),
                         use_case.execute(PreviewTagWriteRequest(('t1',))).changes)
        use_case, *_ = preview_with(track, tags=tags)
        self.assertEqual((TagChange('/music/t1.mp3', 'bpm', '120', '128', True),
                          TagChange('/music/t1.mp3', 'key', None, 'C', False)),
                         use_case.execute(PreviewTagWriteRequest(('t1',), REPLACE_EXISTING)).changes)

    def test_tracks_with_nothing_to_write_are_reported_with_their_reason(self):
        use_case, _, actions, events = preview_with(
            taggable('no-file', location=None), taggable('unreadable'), taggable('weak', detected_bpm=None,
                                                                                 key_strength=0.1),
            unreadable=('/music/unreadable.mp3',))
        preview = use_case.execute(PreviewTagWriteRequest(('no-file', 'unreadable', 'weak', 'absent')))
        self.assertEqual((), preview.changes)
        self.assertIsNone(preview.token)
        self.assertEqual({'no-file': 'No available catalogue location',
                          'unreadable': 'Cannot read the tags of /music/unreadable.mp3: synthetic failure',
                          'weak': 'Nothing to change', 'absent': 'Unknown track'}, dict(preview.skipped))
        self.assertEqual({}, actions.actions)
        self.assertEqual([TagWritePreviewed(None, 0, 4)], events.published)

    def test_an_invalid_request_is_refused_with_a_message_the_listener_can_act_on(self):
        use_case, *_ = preview_with(taggable('t1'))
        too_many = tuple(f't{i}' for i in range(MAXIMUM_TRACKS_PER_ACTION + 1))
        for request, message in [(PreviewTagWriteRequest(()), 'Choose at least one track'),
                                 (PreviewTagWriteRequest(too_many), f'at most {MAXIMUM_TRACKS_PER_ACTION}'),
                                 (PreviewTagWriteRequest(('t1', 't1')), 'more than once'),
                                 (PreviewTagWriteRequest(('t1',), 'overwrite'), 'fill-empty'),
                                 (PreviewTagWriteRequest(('t1',), FILL_EMPTY, 1.5), 'between 0 and 1')]:
            with self.subTest(message=message):
                with self.assertRaisesRegex(TagWriteRequestError, message):
                    use_case.execute(request)


if __name__ == '__main__':
    unittest.main()
