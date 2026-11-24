"""Issue #132: which tag changes one action proposes. Empty values are filled; a different existing value is
replaced only when the listener chose to replace, and the preview shows it as a replacement."""
import unittest

from music_explorer.domain.tag_change_set import (
    FILL_EMPTY, REPLACE_EXISTING, TagChange, TrackTagEvidence, planned_change, planned_track_changes)

LOCATION = '/music/synthetic.flac'


class PlannedChangeTests(unittest.TestCase):
    def test_an_empty_tag_is_filled(self):
        for current in (None, '', '  '):
            with self.subTest(current=current):
                self.assertEqual(TagChange(LOCATION, 'bpm', current, '124', replaces=False),
                                 planned_change(LOCATION, 'bpm', current, '124', FILL_EMPTY))

    def test_a_different_existing_value_is_kept_unless_replacing_was_chosen(self):
        self.assertIsNone(planned_change(LOCATION, 'key', 'Am', 'C', FILL_EMPTY))
        self.assertEqual(TagChange(LOCATION, 'key', 'Am', 'C', replaces=True),
                         planned_change(LOCATION, 'key', 'Am', 'C', REPLACE_EXISTING))

    def test_nothing_changes_when_the_value_is_already_there_or_unknown(self):
        for policy in (FILL_EMPTY, REPLACE_EXISTING):
            with self.subTest(policy=policy):
                self.assertIsNone(planned_change(LOCATION, 'bpm', '124', '124', policy))
                self.assertIsNone(planned_change(LOCATION, 'bpm', '', None, policy))
                self.assertIsNone(planned_change(LOCATION, 'bpm', 'old', '', policy))

    def test_an_unknown_policy_is_refused(self):
        with self.assertRaises(ValueError):
            planned_change(LOCATION, 'bpm', '', '124', 'overwrite-everything')

    def test_equal_change_sets_compare_equal_so_a_stale_preview_is_detectable(self):
        first = (planned_change(LOCATION, 'bpm', '', '124', FILL_EMPTY),)
        self.assertEqual(first, (planned_change(LOCATION, 'bpm', '', '124', FILL_EMPTY),))
        self.assertNotEqual(first, (planned_change(LOCATION, 'bpm', '', '125', FILL_EMPTY),))
        self.assertNotEqual(first, (planned_change(LOCATION, 'bpm', None, '124', FILL_EMPTY),))


class PlannedTrackChangesTests(unittest.TestCase):
    def evidence(self, **values):
        defaults = dict(location=LOCATION, detected_bpm=123.6, tonic='A', scale='minor', key_strength=0.9,
                        manual_bpm=None, manual_key=None)
        return TrackTagEvidence(**{**defaults, **values})

    def test_bpm_and_key_are_planned_from_the_evidence_in_field_order(self):
        self.assertEqual((TagChange(LOCATION, 'bpm', None, '124', replaces=False),
                          TagChange(LOCATION, 'key', None, 'Am', replaces=False)),
                         planned_track_changes(self.evidence(), current_bpm=None, current_key=None,
                                               policy=FILL_EMPTY, minimum_key_strength=0.5))

    def test_overrides_win_weak_keys_write_nothing_and_existing_values_are_respected(self):
        changes = planned_track_changes(self.evidence(manual_bpm='128', key_strength=0.2), current_bpm='120',
                                        current_key=None, policy=FILL_EMPTY, minimum_key_strength=0.5)
        self.assertEqual((), changes)
        changes = planned_track_changes(self.evidence(manual_bpm='128', key_strength=0.2), current_bpm='120',
                                        current_key=None, policy=REPLACE_EXISTING, minimum_key_strength=0.5)
        self.assertEqual((TagChange(LOCATION, 'bpm', '120', '128', replaces=True),), changes)


if __name__ == '__main__':
    unittest.main()
