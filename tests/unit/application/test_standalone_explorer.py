import unittest

from music_explorer.application.dto.explorer import AnalysisReport, ExplorerMetadata, ExplorerStoredTrack, ExplorerTrackSummary, StageResult
from music_explorer.application.use_cases.explorer import ListExplorerTrackSummaries, ListExplorerTracks, ListExplorerTrackSummaries


class FakeExplorerRepository:
    def __init__(self):
        self.records = (
            ExplorerStoredTrack(
                track_id='sha256:' + 'a' * 64,
                sha256='a' * 64,
                size=123,
                display_label='A Song.flac',
                available_locations=1,
                run=AnalysisReport('run', 'completed', (StageResult('bpm', (), '', (('bpm', 120.0),)),)),
                overrides=(),
            ),
        )

    def metadata(self):
        return {'application_id': 0x4D414E41, 'schema_version': 4, 'read_policy': 'bounded_read_transaction'}

    def list_tracks(self, limit, after=None):
        return self.metadata(), len(self.records), self.records[:limit]

    def list_track_summaries(self, limit, cursor=None, query='', order='title'):
        from music_explorer.application.dto.explorer import ExplorerTrackSummary
        records = self.records
        summaries = tuple(ExplorerTrackSummary(r.track_id, r.display_label, 'Unknown artist', r.display_label, r.available_locations) for r in records[:limit])
        return self.metadata(), len(records), summaries, None

    def list_track_summaries(self, limit, cursor=None, query='', order='title'):
        self.summary_args = (limit, cursor, query, order)
        rows = (ExplorerTrackSummary('sha256:' + 'a' * 64, 'A Song', 'Artist', 'A Song.flac', 1),)
        return self.metadata(), len(rows), rows[:limit], None


class StandaloneExplorerUseCaseTests(unittest.TestCase):
    def test_summary_page_uses_compact_repository_boundary(self):
        repo = FakeExplorerRepository()
        page = ListExplorerTrackSummaries(repo).execute(limit=1, cursor='c', query=' a ', order='id')

        self.assertEqual(repo.summary_args, (1, 'c', 'a', 'id'))
        self.assertEqual(page.tracks[0].title, 'A Song')
        self.assertEqual(page.next_cursor, None)

    def test_list_metadata_keeps_existing_summary_feature_contract_version(self):
        report = ListExplorerTracks(FakeExplorerRepository()).execute(limit=10)

        self.assertIsInstance(report.metadata, ExplorerMetadata)
        self.assertEqual(report.metadata.feature_contract_version, 'summary-derived-v1')

    def test_summary_page_keeps_existing_summary_feature_contract_version(self):
        page = ListExplorerTrackSummaries(FakeExplorerRepository()).execute(limit=1)

        self.assertEqual(page.metadata.feature_contract_version, 'summary-derived-v1')
        self.assertEqual(page.tracks[0].title, 'A Song')


if __name__ == '__main__':
    unittest.main()
