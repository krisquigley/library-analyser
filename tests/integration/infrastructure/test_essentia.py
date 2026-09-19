import unittest
from types import SimpleNamespace
from music_analyzer.application.dto.analysis import AnalysisError, DecodedAudio
from music_analyzer.infrastructure.analysis.essentia import EssentiaEngine, sample_regions
from music_analyzer.infrastructure.models.manifest import load_manifest


class Library:
    def __init__(self):
        self.calls = []
        self.bad = False
    def __getattr__(self, name):
        def construct(**kwargs):
            self.calls.append((name, kwargs))
            def run(audio):
                if name == 'RhythmExtractor2013': return (123, [], 2.5, [], [])
                if name == 'KeyExtractor': return ('C', 'minor', .7)
                if name == 'TensorflowPredict2D':
                    model = kwargs['graphFilename']
                    width = len(load_manifest()[model]['metadata']['classes'])
                    return [[float('nan') if self.bad else .2] * width]
                return [[.1] * (200 if name == 'TensorflowPredictMusiCNN' else 1280)]
            return run
        return construct


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.library = Library()
        self.engine = EssentiaEngine(self.library, 'test-version', load_manifest(),
            lambda model: (model, 'abc'), lambda audio, start, end, rate: [0.0])
        self.audio = DecodedAudio('opaque', 120, 44100)

    def test_disjoint_sampling_bounded_and_short_track(self):
        self.assertEqual(sample_regions(120), ((0, 30), (45, 75), (90, 120)))
        self.assertEqual(sample_regions(20), ((0, 20),))
        self.assertEqual(sample_regions(60), ((0, 60),))

    def test_rhythm_and_key_map_native_strength_without_probability(self):
        bpm = self.engine.analyze('bpm', self.audio)
        key = self.engine.analyze('key', self.audio)
        self.assertIn(('bpm', 123.0), bpm.values)
        self.assertIn(('strength', .7), key.values)
        self.assertIn('not calibrated', bpm.uncertainty)

    def test_semantics_share_embeddings_use_metadata_tensors_and_coverage(self):
        for stage in ('genres', 'mood', 'instruments', 'energy'):
            result = self.engine.analyze(stage, self.audio)
            self.assertEqual(result.summary.coverage, .75)
            self.assertEqual(len(result.windows), 3)
            self.assertTrue(result.summary.provisional)
        calls = self.library.calls
        self.assertEqual(sum(name == 'TensorflowPredictEffnetDiscogs' for name, _ in calls), 1)
        eff = next(kw for name, kw in calls if name == 'TensorflowPredictEffnetDiscogs')
        self.assertEqual(eff['output'], 'PartitionedCall:1')
        self.assertEqual(eff['batchSize'], 64)
        self.assertEqual(eff['lastBatchMode'], 'same')
        head = next(kw for name, kw in calls if name == 'TensorflowPredict2D')
        self.assertEqual(head['dimensions'], 1280)
        energy = self.engine.analyze('energy', self.audio)
        self.assertEqual(energy.summary.labels, ('valence', 'arousal'))
        self.assertIn('arousal', energy.uncertainty)

    def test_nonfinite_output_is_actionable_failure(self):
        self.library.bad = True
        with self.assertRaisesRegex(AnalysisError, 'genres.*output'):
            self.engine.analyze('genres', self.audio)

    def test_library_failure_is_not_fake_result(self):
        self.engine.library = SimpleNamespace(RhythmExtractor2013=lambda **kw: (_ for _ in ()).throw(RuntimeError('missing')))
        with self.assertRaisesRegex(AnalysisError, 'Essentia.*bpm'):
            self.engine.analyze('bpm', self.audio)

    def test_empty_embedding_output_fails_before_classifier(self):
        self.engine._predictor = lambda model, purpose: lambda signal: []
        with self.assertRaisesRegex(AnalysisError, 'embedding output'):
            self.engine.analyze('genres', self.audio)

    def test_changed_track_does_not_reuse_embeddings(self):
        reads = []
        self.engine.read_audio = lambda *args: reads.append(args) or [0.0]
        self.engine.analyze('genres', self.audio)
        self.engine.analyze('mood', self.audio)
        self.assertEqual(len(reads), 3)
        self.engine.analyze('mood', DecodedAudio('other', 120, 44100))
        self.assertEqual(len(reads), 6)
