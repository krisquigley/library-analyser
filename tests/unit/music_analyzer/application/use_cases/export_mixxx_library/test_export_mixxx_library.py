"""Issue #133: export the active analysed tracks to a new Mixxx-compatible library file, overrides winning."""
import unittest

from music_analyzer.application.dto.analysis import AnalysisReport, StageResult
from music_analyzer.application.dto.catalogue import TrackMetadata
from music_analyzer.application.dto.review import StoredTrack
from music_analyzer.application.use_cases.export_mixxx_library.export_mixxx_library import (
    ExportMixxxLibrary, ExportMixxxLibraryRequest, MixxxLibraryExported, MixxxLibraryExportPlanned)
from music_analyzer.application.use_cases.export_mixxx_library.export_mixxx_library import MOOD_QUADRANT_COLOURS
from music_analyzer.domain.analysis import ScoreSummary
from music_analyzer.domain.mixxx_library import MixxxExportError, MixxxKey
from music_analyzer.domain.mood_colour import CALM, SOMBRE, TENSE, UPBEAT

DESTINATION = '/exports/new-mixxx.sqlite'
PROBED = TrackMetadata(duration_seconds=200.0, duration_source='mutagen')


def analysed(track_id, *, bpm=124.0, key=('A', 'minor'), location=None, overrides=(), duration=300.0,
             status='completed', mood=None, mood_model='emomusic-msd-musicnn-2', common=(('title', 'Synthetic Title'), ('artist', ('Artist One', 'Artist Two')),
                                         ('album', 'Synthetic Album'))):
    stages = (StageResult('bpm', (), '', (('bpm', bpm), ('confidence', 3.0))),
              StageResult('key', (), '', (('key', key[0]), ('scale', key[1]), ('strength', 0.8))))
    if mood is not None:
        valence, arousal = mood
        summary = ScoreSummary(('valence', 'arousal'), (valence, arousal), (valence, arousal), (valence, arousal), 1.0)
        stages += (StageResult('energy', (('model', mood_model),), '', summary=summary),)
    locations = (location,) if location is not None else (f'/music/{track_id}.flac',)
    if location == '':
        locations = ()
    return StoredTrack(track_id, 'sha', 1000, locations, AnalysisReport('run', status, stages), tuple(overrides),
                       TrackMetadata(common=common, duration_seconds=duration, duration_source='mutagen'))


class FakeTracks:
    def __init__(self, *tracks):
        self.tracks = {track.track_id: track for track in tracks}

    def track_ids(self):
        return iter(self.tracks)

    def read_track(self, track_id):
        if track_id not in self.tracks:
            raise ValueError(f'Unknown track ID {track_id}')
        return self.tracks[track_id]


class FakeLibraryExport:
    def __init__(self, occupied=()):
        self.occupied_paths, self.created = set(occupied), []

    def occupied(self, destination):
        return destination in self.occupied_paths

    def create(self, destination, tracks):
        self.created.append((destination, tracks))


class FakeEvents:
    def __init__(self):
        self.published = []

    def publish(self, event):
        self.published.append(event)


def export_with(*tracks, occupied=()):
    library_export, events = FakeLibraryExport(occupied), FakeEvents()
    return ExportMixxxLibrary(FakeTracks(*tracks), library_export, events), library_export, events


class ExportMixxxLibraryTests(unittest.TestCase):
    def test_an_analysed_track_becomes_a_mixxx_row_from_its_evidence(self):
        use_case, library_export, events = export_with(analysed('t1'))
        plan = use_case.export(ExportMixxxLibraryRequest(DESTINATION))
        (track,) = plan.tracks
        self.assertEqual(('/music/t1.flac', 't1.flac', '/music'),
                         (track.location.location, track.location.filename, track.location.directory))
        self.assertEqual((1000, 'Synthetic Title', 'Artist One; Artist Two', 'Synthetic Album', 300.0, 124.0),
                         (track.filesize, track.title, track.artist, track.album, track.duration, track.bpm))
        self.assertEqual((MixxxKey(22, 'Am'), 'flac'), (track.key, track.file_type))
        self.assertEqual([(DESTINATION, plan.tracks)], library_export.created)
        self.assertEqual([MixxxLibraryExported(DESTINATION, 1, 0)], events.published)

    def test_manual_overrides_win_over_the_detected_bpm_and_key(self):
        use_case, _, _ = export_with(analysed('t1', overrides=(('bpm', '128'), ('key', 'C#m'))))
        (track,) = use_case.export(ExportMixxxLibraryRequest(DESTINATION)).tracks
        self.assertEqual((128.0, MixxxKey(14, 'C#m')), (track.bpm, track.key))

    def test_unknown_values_are_left_empty(self):
        use_case, _, _ = export_with(analysed('t1', bpm=float('nan'), key=('X', 'modal'), common=(),
                                              location='/music/noextension'))
        (track,) = use_case.export(ExportMixxxLibraryRequest(DESTINATION)).tracks
        self.assertEqual(('', '', '', 0.0, MixxxKey(0, ''), '?'),
                         (track.title, track.artist, track.album, track.bpm, track.key, track.file_type))

    def test_tracks_that_are_not_active_and_analysed_are_skipped_with_their_reason(self):
        use_case, library_export, events = export_with(
            analysed('kept'), analysed('missing', location=''), analysed('failed', status='failed'),
            analysed('too-long', duration=2000.0),
            StoredTrack('unanalysed', 'sha', 1, ('/music/u.flac',), None, (), PROBED))
        plan = use_case.export(ExportMixxxLibraryRequest(DESTINATION))
        self.assertEqual(['kept'], [track.location.filename.removesuffix('.flac') for track in plan.tracks])
        self.assertEqual({'missing': 'No available catalogue location', 'failed': 'Latest analysis run: failed',
                          'unanalysed': 'Not analysed yet',
                          'too-long': 'Excluded from active library: duration exceeds 1200.0s; excluded from active '
                                      'library; rescan metadata or choose a shorter file'}, dict(plan.skipped))
        self.assertEqual([MixxxLibraryExported(DESTINATION, 1, 4)], events.published)

    def test_chosen_tracks_are_exported_once_each_in_the_order_given(self):
        use_case, _, _ = export_with(analysed('a'), analysed('b'), analysed('c'))
        plan = use_case.export(ExportMixxxLibraryRequest(DESTINATION, ('c', 'a', 'c')))
        self.assertEqual(['c.flac', 'a.flac'], [track.location.filename for track in plan.tracks])

    def test_a_dry_run_plans_the_export_and_writes_nothing(self):
        use_case, library_export, events = export_with(analysed('t1'), StoredTrack('u', 'sha', 1, (), None))
        plan = use_case.preview(ExportMixxxLibraryRequest(DESTINATION))
        self.assertEqual((1, 1), (len(plan.tracks), len(plan.skipped)))
        self.assertEqual([], library_export.created)
        self.assertEqual([MixxxLibraryExportPlanned(DESTINATION, 1, 1)], events.published)

    def test_an_existing_destination_is_refused_before_anything_is_written(self):
        for run in ('export', 'preview'):
            with self.subTest(run=run):
                use_case, library_export, events = export_with(analysed('t1'), occupied=(DESTINATION,))
                with self.assertRaisesRegex(MixxxExportError, 'already exists'):
                    getattr(use_case, run)(ExportMixxxLibraryRequest(DESTINATION))
                self.assertEqual(([], []), (library_export.created, events.published))

    def test_an_export_with_no_track_to_write_is_refused(self):
        use_case, library_export, _ = export_with(StoredTrack('u', 'sha', 1, (), None))
        with self.assertRaisesRegex(MixxxExportError, 'No active analysed track'):
            use_case.export(ExportMixxxLibraryRequest(DESTINATION))
        self.assertEqual([], library_export.created)


class MoodQuadrantColourTests(unittest.TestCase):
    def colours(self, *tracks, request=ExportMixxxLibraryRequest(DESTINATION, (), MOOD_QUADRANT_COLOURS)):
        use_case, _, _ = export_with(*tracks)
        plan = use_case.export(request)
        return plan, {track.location.filename.removesuffix('.flac'): track.color for track in plan.tracks}

    def test_each_track_is_coloured_by_its_quadrant_among_the_exported_tracks(self):
        plan, colours = self.colours(analysed('upbeat', mood=(6.0, 6.5)), analysed('tense', mood=(3.0, 7.0)),
                                     analysed('middle', mood=(4.5, 5.0)), analysed('calm', mood=(7.0, 2.0)),
                                     analysed('sombre', mood=(2.0, 3.0)))
        self.assertEqual({'upbeat': UPBEAT.rgb, 'tense': TENSE.rgb, 'middle': None, 'calm': CALM.rgb,
                          'sombre': SOMBRE.rgb}, colours)
        self.assertEqual(5, plan.colour_population)
        self.assertEqual(((UPBEAT.name, 1), (TENSE.name, 1), (CALM.name, 1), (SOMBRE.name, 1), ('no colour', 1)),
                         plan.colour_counts)

    def test_unknown_incompatible_or_overridden_mood_gets_no_colour_and_is_left_out_of_the_ranks(self):
        plan, colours = self.colours(
            analysed('high', mood=(6.0, 6.0)), analysed('low', mood=(1.0, 1.0)), analysed('none'),
            analysed('other-model', mood=(9.0, 9.0), mood_model='another-model'),
            analysed('energy-override', mood=(9.0, 9.0), overrides=(('energy', 'high'),)),
            analysed('mood-override', mood=(9.0, 9.0), overrides=(('mood', 'happy'),)),
            analysed('nan', mood=(float('nan'), 1.0)))
        self.assertEqual({'high': UPBEAT.rgb, 'low': SOMBRE.rgb, 'none': None, 'other-model': None,
                          'energy-override': None, 'mood-override': None, 'nan': None}, colours)
        self.assertEqual(2, plan.colour_population)

    def test_a_lone_track_sits_at_the_median_and_gets_no_colour(self):
        _, colours = self.colours(analysed('alone', mood=(5.0, 5.0)))
        self.assertEqual({'alone': None}, colours)

    def test_without_the_colour_option_no_track_is_coloured(self):
        plan, colours = self.colours(analysed('a', mood=(6.0, 6.0)), analysed('b', mood=(1.0, 1.0)),
                                     request=ExportMixxxLibraryRequest(DESTINATION))
        self.assertEqual({'a': None, 'b': None}, colours)
        self.assertEqual((0, ()), (plan.colour_population, plan.colour_counts))

    def test_an_unknown_colouring_is_refused(self):
        use_case, _, _ = export_with(analysed('a'))
        with self.assertRaisesRegex(MixxxExportError, 'mood-quadrant'):
            use_case.preview(ExportMixxxLibraryRequest(DESTINATION, (), 'rainbow'))


if __name__ == '__main__':
    unittest.main()
