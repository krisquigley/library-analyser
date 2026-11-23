"""Issue #133: export the active analysed tracks to a new Mixxx-compatible library file, overrides winning."""
import unittest

from music_analyzer.application.dto.analysis import AnalysisReport, StageResult
from music_analyzer.application.dto.catalogue import TrackMetadata
from music_analyzer.application.dto.review import StoredTrack
from music_analyzer.application.use_cases.export_mixxx_library.export_mixxx_library import (
    ExportMixxxLibrary, ExportMixxxLibraryRequest, MixxxLibraryExported, MixxxLibraryExportPlanned)
from music_analyzer.domain.mixxx_library import MixxxExportError, MixxxKey

DESTINATION = '/exports/new-mixxx.sqlite'
PROBED = TrackMetadata(duration_seconds=200.0, duration_source='mutagen')


def analysed(track_id, *, bpm=124.0, key=('A', 'minor'), location=None, overrides=(), duration=300.0,
             status='completed', common=(('title', 'Synthetic Title'), ('artist', ('Artist One', 'Artist Two')),
                                         ('album', 'Synthetic Album'))):
    stages = (StageResult('bpm', (), '', (('bpm', bpm), ('confidence', 3.0))),
              StageResult('key', (), '', (('key', key[0]), ('scale', key[1]), ('strength', 0.8))))
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


if __name__ == '__main__':
    unittest.main()
