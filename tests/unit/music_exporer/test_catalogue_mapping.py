import unittest

from music_analyzer.application.dto.analysis import AnalysisReport, StageResult
from music_analyzer.application.dto.explorer import ExplorerStoredTrack
from music_analyzer.domain.analysis import ScoreSummary
from music_exporer.interface_adapters.catalogue_contract import map_analyzer_track


class CatalogueContractMappingTests(unittest.TestCase):
    def test_maps_analyzer_read_model_to_explorer_owned_track_without_paths(self):
        source = ExplorerStoredTrack(
            track_id='sha256:' + 'a' * 64,
            sha256='a' * 64,
            size=123,
            display_label='Private Song.flac',
            available_locations=2,
            run=AnalysisReport(
                'run-1', 'completed',
                (StageResult('bpm', (), '', (('bpm', 128.0),)),
                 StageResult('energy', (('model', 'emomusic-msd-musicnn-2'),), '', (), (), ScoreSummary(('valence', 'arousal'), (0.7, 0.2), (0.7, 0.2), (0.7, 0.2), 1.0))),
                ''),
            overrides=(('mood', 'manual text'),),
        )

        mapped = map_analyzer_track(source)

        self.assertEqual(mapped.track_id, source.track_id)
        self.assertEqual(mapped.display_label, 'Private Song.flac')
        self.assertEqual(mapped.available_locations, 2)
        self.assertEqual(mapped.overrides, (('mood', 'manual text'),))
        self.assertEqual(mapped.run.status, 'completed')
        self.assertEqual(mapped.run.stages[1].summary.labels, ('valence', 'arousal'))
        self.assertNotIn('/private/', repr(mapped))
        self.assertEqual(type(mapped).__module__.split('.')[0], 'music_exporer')


if __name__ == '__main__':
    unittest.main()
