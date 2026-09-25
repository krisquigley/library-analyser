import unittest

from music_analyzer.application.dto.analysis import AnalysisReport, StageResult
from music_analyzer.application.dto.catalogue import TrackMetadata
from music_analyzer.application.dto.explorer import ExplorerMetadata, ExplorerStoredTrack
from music_analyzer.application.use_cases.explorer import GetExplorerTrackDetail, ListExplorerTracks


class FakeExplorerRepository:
    def __init__(self):
        self.records = (
            ExplorerStoredTrack(
                track_id='sha256:' + 'a' * 64,
                sha256='a' * 64,
                size=123,
                display_label='A Song.flac',
                available_locations=1,
                run=AnalysisReport('new-failed', 'failed', (StageResult('bpm', (), 'uncertain', (('bpm', 120.0),)),), 'decode failed'),
                overrides=(('bpm', 'about 128 maybe'),),
                metadata=TrackMetadata(common=(('title', 'Tagged Song'),), tags=(('TITLE', ('Tagged Song',)),)),
            ),
            ExplorerStoredTrack(
                track_id='sha256:' + 'b' * 64,
                sha256='b' * 64,
                size=456,
                display_label='',
                available_locations=0,
                run=None,
                overrides=(),
            ),
        )

    def metadata(self):
        return {'application_id': 0x4D414E41, 'schema_version': 4, 'read_policy': 'bounded_read_transaction'}

    def track_ids(self):
        return tuple(record.track_id for record in self.records)

    def list_tracks(self, limit, after=None):
        records = self.records
        if after is not None:
            records = tuple(record for record in records if record.track_id > after)
        return self.metadata(), len(records), records[:limit]

    def read_track(self, track_id):
        for record in self.records:
            if record.track_id == track_id:
                return record
        raise AssertionError('unexpected track lookup')


class ExplorerUseCaseTests(unittest.TestCase):
    def setUp(self):
        self.reader = FakeExplorerRepository()

    def test_list_returns_redacted_summaries_without_paths_or_raw_predictions(self):
        report = ListExplorerTracks(self.reader).execute(limit=10)
        self.assertIsInstance(report.metadata, ExplorerMetadata)
        self.assertEqual(report.metadata.schema_version, 4)
        self.assertEqual(len(report.tracks), 2)
        first = report.tracks[0]
        self.assertEqual(first.handle, 'sha256:' + 'a' * 64)
        self.assertEqual(first.display_label, 'A Song.flac')
        self.assertEqual(first.available_locations, 1)
        self.assertEqual(first.latest_run_status, 'failed')
        self.assertEqual(first.latest_run_detail, '')
        self.assertEqual(first.fields['bpm'].automatic_values, (('bpm', 120.0),))
        self.assertEqual(first.fields['bpm'].manual_text, 'about 128 maybe')
        self.assertEqual(first.fields['bpm'].effective_source, 'manual_text')
        self.assertTrue(first.fields['bpm'].typed_unresolved)
        self.assertNotIn('/private/music', repr(first))
        self.assertNotIn('raw_predictions', repr(first))
        self.assertIn('Latest run: failed', first.reasons)

    def test_detail_preserves_persisted_embedded_metadata(self):
        report = GetExplorerTrackDetail(self.reader).execute('sha256:' + 'a' * 64)
        self.assertEqual(report.metadata.common, (('title', 'Tagged Song'),))
        self.assertEqual(report.metadata.tags, (('TITLE', ('Tagged Song',)),))

    def test_detail_preserves_missing_identity_linked_evidence_and_unavailable_location(self):
        report = GetExplorerTrackDetail(self.reader).execute('sha256:' + 'b' * 64)
        self.assertEqual(report.handle, 'sha256:' + 'b' * 64)
        self.assertEqual(report.available_locations, 0)
        self.assertEqual(report.latest_run_status, None)
        self.assertIn('No available catalogue location', report.reasons)
        self.assertIn('No identity-linked analysis; legacy/path-only runs are not attributed', report.reasons)
        self.assertEqual(report.fields['key'].effective_source, 'missing')
        self.assertEqual(report.fields['key'].missing_reasons, ('key: missing result',))

    def test_limit_is_bounded_at_application_boundary(self):
        with self.assertRaises(ValueError):
            ListExplorerTracks(self.reader).execute(limit=0)
        with self.assertRaises(ValueError):
            ListExplorerTracks(self.reader).execute(limit=501)

    def test_unknown_detail_handle_is_actionable(self):
        with self.assertRaises(ValueError):
            GetExplorerTrackDetail(self.reader).execute('missing')

    def test_list_uses_single_repository_snapshot_boundary(self):
        class SnapshotOnlyRepository(FakeExplorerRepository):
            def track_ids(self):  # pragma: no cover - must not be used for list assembly
                raise AssertionError('list must not assemble tracks across separate repository calls')

            def read_track(self, track_id):  # pragma: no cover - must not be used for list assembly
                raise AssertionError('list must not assemble tracks across separate repository calls')

        report = ListExplorerTracks(SnapshotOnlyRepository()).execute(limit=1)
        self.assertEqual(report.metadata.track_count, 2)
        self.assertEqual(tuple(track.handle for track in report.tracks), ('sha256:' + 'a' * 64,))


if __name__ == '__main__':
    unittest.main()
