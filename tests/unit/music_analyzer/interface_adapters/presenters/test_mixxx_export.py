"""Issue #133: what the listener reads after `music-analyzer export-mixxx`, with and without --dry-run."""
import unittest

from music_analyzer.application.use_cases.export_mixxx_library.export_mixxx_library import (
    MixxxLibraryExportPlan, MixxxLibraryExported, MixxxLibraryExportPlanned)
from music_analyzer.interface_adapters.presenters.mixxx_export import (
    present_mixxx_export_planned, present_mixxx_exported, present_mood_colours, present_skipped_tracks)


class MixxxExportPresenterTests(unittest.TestCase):
    def test_a_dry_run_says_what_would_be_written_and_writes_nothing(self):
        self.assertEqual('Dry run: would export 2 tracks to /exports/new.sqlite (Mixxx 2.5, schema 39); '
                         '1 skipped. Nothing was written.',
                         present_mixxx_export_planned(MixxxLibraryExportPlanned('/exports/new.sqlite', 2, 1)))

    def test_an_export_says_what_was_written(self):
        self.assertEqual('Exported 1 track to /exports/new.sqlite (Mixxx 2.5, schema 39); 0 skipped.',
                         present_mixxx_exported(MixxxLibraryExported('/exports/new.sqlite', 1, 0)))

    def test_each_skipped_track_is_listed_with_its_reason(self):
        self.assertEqual('Skipped t1: Not analysed yet\nSkipped t2: No available catalogue location',
                         present_skipped_tracks((('t1', 'Not analysed yet'), ('t2', 'No available catalogue location'))))
        self.assertEqual('', present_skipped_tracks(()))


    def test_the_mood_colours_say_how_many_tracks_get_each_and_over_which_population(self):
        plan = MixxxLibraryExportPlan('/x', (), (), 3, (('upbeat (high arousal, high valence)', 2), ('no colour', 2)))
        self.assertEqual('Mood-quadrant colours, relative to the 3 exported tracks with valence and arousal '
                         '(provisional, uncalibrated scores):\n'
                         '  upbeat (high arousal, high valence): 2\n  no colour: 2', present_mood_colours(plan))
        self.assertEqual('', present_mood_colours(MixxxLibraryExportPlan('/x', (), ())))


if __name__ == '__main__':
    unittest.main()
