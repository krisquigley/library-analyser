import unittest

from music_exporer.application.dto.explorer import AnalysisReport, ExplorerMetadata, ExplorerStoredTrack, StageResult
from music_exporer.application.use_cases.explorer import ListExplorerTracks


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


class StandaloneExplorerUseCaseTests(unittest.TestCase):
    def test_list_metadata_keeps_existing_summary_feature_contract_version(self):
        report = ListExplorerTracks(FakeExplorerRepository()).execute(limit=10)

        self.assertIsInstance(report.metadata, ExplorerMetadata)
        self.assertEqual(report.metadata.feature_contract_version, 'summary-derived-v1')


if __name__ == '__main__':
    unittest.main()
