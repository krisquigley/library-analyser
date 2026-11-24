"""Issue #132: applying an approved tag-write action writes exactly what was previewed, once, and reports
every file's outcome; a stale, unknown or spent approval writes nothing."""
import unittest

from music_explorer.application.ports.track_tags import OwnedTags
from music_explorer.application.use_cases.apply_tag_write.apply_tag_write import (
    RESCAN_NOTICE, ApplyTagWrite, TagWriteApplied, TagWriteApprovalError, TagWriteOutcome, TagWriteRejected)
from music_explorer.application.use_cases.preview_tag_write.preview_tag_write import (
    PreviewTagWrite, PreviewTagWriteRequest)
from tests.unit.music_explorer.application.use_cases.tag_write_fakes import (
    FakeEvents, FakeFileIdentity, FakeTaggableTracks, FakeTagWriteActions, FakeTrackTags, taggable)


class ApplyTagWriteTests(unittest.TestCase):
    def setUp(self):
        self.tracks = FakeTaggableTracks(taggable('t1'), taggable('t2'))
        self.track_tags, self.actions, self.events = FakeTrackTags(), FakeTagWriteActions(), FakeEvents()

    def preview(self, *track_ids):
        preview = PreviewTagWrite(self.tracks, self.track_tags, self.actions, self.events)
        return preview.execute(PreviewTagWriteRequest(track_ids or ('t1', 't2'))).token

    def apply(self, token, changed=()):
        identity = FakeFileIdentity(self.tracks, changed)
        return ApplyTagWrite(self.tracks, self.track_tags, identity, self.actions, self.events).execute(token)

    def test_an_approved_action_writes_the_previewed_fields_and_reports_each_file(self):
        report = self.apply(self.preview())
        self.assertEqual([('/music/t1.mp3', OwnedTags('124', 'Am')), ('/music/t2.mp3', OwnedTags('124', 'Am'))],
                         self.track_tags.writes)
        self.assertEqual((TagWriteOutcome('/music/t1.mp3', 'written', 'BPM 124, key Am'),
                          TagWriteOutcome('/music/t2.mp3', 'written', 'BPM 124, key Am')), report.outcomes)
        self.assertEqual(RESCAN_NOTICE, report.notice)
        self.assertEqual('applied', self.actions.find('token-1').state)
        self.assertEqual(TagWriteApplied('token-1', 2, 0, 0), self.events.published[-1])

    def test_an_approval_is_spent_once_used(self):
        token = self.preview()
        self.apply(token)
        with self.assertRaisesRegex(TagWriteApprovalError, 'already been used'):
            self.apply(token)
        self.assertEqual(2, len(self.track_tags.writes))

    def test_an_unknown_or_missing_token_writes_nothing(self):
        for token in ('forged', '', None):
            with self.subTest(token=token):
                with self.assertRaisesRegex(TagWriteApprovalError, 'preview again'):
                    self.apply(token)
        self.assertEqual([], self.track_tags.writes)

    def test_a_tag_changed_since_the_preview_rejects_the_whole_action(self):
        token = self.preview()
        self.track_tags.tags['/music/t2.mp3'] = OwnedTags('99', None)
        with self.assertRaisesRegex(TagWriteApprovalError, 'changed since the preview'):
            self.apply(token)
        self.assertEqual([], self.track_tags.writes)
        self.assertEqual('rejected', self.actions.find(token).state)
        self.assertEqual(TagWriteRejected(token, 'changed since the preview'), self.events.published[-1])
        with self.assertRaisesRegex(TagWriteApprovalError, 'already been used'):
            self.apply(token)

    def test_a_file_changed_since_analysis_is_skipped_and_a_failed_write_reported(self):
        token = self.preview()
        self.track_tags.unwritable.add('/music/t2.mp3')
        report = self.apply(token, changed=('/music/t1.mp3',))
        self.assertEqual((TagWriteOutcome('/music/t1.mp3', 'skipped',
                                          'The file changed since it was analysed: rescan it, then preview again'),
                          TagWriteOutcome('/music/t2.mp3', 'failed',
                                          'Cannot write the tags of /music/t2.mp3: synthetic failure')),
                         report.outcomes)
        self.assertEqual('', report.notice)
        self.assertEqual(TagWriteApplied(token, 0, 1, 1), self.events.published[-1])


if __name__ == '__main__':
    unittest.main()
