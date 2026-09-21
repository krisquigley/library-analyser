from contextlib import contextmanager
import unittest

from music_analyzer.application.use_cases.analyze_track import AnalyzeTrack
from music_analyzer.application.dto.analysis import AnalysisError, AudioSource, DecodedAudio, StageResult


class Decoder:
    def __init__(self, events):
        self.events = events

    @contextmanager
    def decode(self, source, max_duration):
        self.events.append(('decode', source, max_duration))
        try:
            yield DecodedAudio('private-handle', 10, 44100)
        finally:
            self.events.append('cleanup')


class Engine:
    def __init__(self, events, fail=None):
        self.events, self.fail = events, fail

    def analyze(self, stage, audio):
        self.events.append(('engine', stage))
        if stage == self.fail:
            raise AnalysisError('engine unavailable')
        return StageResult(stage, (('engine', 'fake-test-only'),), 'fixture only')


class Repository:
    def __init__(self, events):
        self.events = events

    def start(self, source):
        self.events.append(('start', source))
        return 'run-1'

    def save_stage(self, run_id, result):
        self.events.append(('saved', result.stage))

    def finish(self, run_id, status, detail):
        self.events.append(('finish', status, detail))


class AnalyzeTrackTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.source = AudioSource('/read-only/track.flac')

    def build(self, fail=None):
        return AnalyzeTrack(Decoder(self.events), Engine(self.events, fail), Repository(self.events))

    def test_all_six_stages_checkpoint_before_next_stage_and_cleanup(self):
        report = self.build().execute(self.source, max_duration=60)
        self.assertEqual(report.run_id, 'run-1')
        self.assertEqual(report.status, 'completed')
        self.assertEqual(tuple(r.stage for r in report.stages),
                         ('bpm', 'key', 'genres', 'mood', 'instruments', 'energy'))
        for i, stage in enumerate(report.stages):
            position = self.events.index(('engine', stage.stage))
            self.assertEqual(self.events[position + 1], ('saved', stage.stage))
        self.assertEqual(self.events[-2:], ['cleanup', ('finish', 'completed', '')])

    def test_failure_preserves_completed_stages_and_reports_no_fabricated_results(self):
        report = self.build(fail='genres').execute(self.source)
        self.assertEqual(report.status, 'failed')
        self.assertEqual(tuple(r.stage for r in report.stages), ('bpm', 'key'))
        self.assertEqual(report.detail, 'genres: engine unavailable')
        self.assertIn('cleanup', self.events)
        self.assertNotIn(('engine', 'mood'), self.events)

    def test_decode_failure_and_interrupt_are_recorded(self):
        for error, status in [(AnalysisError('bad audio'), 'failed'), (KeyboardInterrupt(), 'interrupted')]:
            class FailingDecoder:
                def decode(self, source, max_duration):
                    raise error
            use_case = AnalyzeTrack(FailingDecoder(), Engine(self.events), Repository(self.events))
            if status == 'interrupted':
                with self.assertRaises(KeyboardInterrupt):
                    use_case.execute(self.source)
            else:
                self.assertEqual(use_case.execute(self.source).status, status)
            self.assertEqual(self.events[-1][1], status)

    def test_invalid_limit_has_no_side_effects(self):
        for value in (0, -1, float('inf'), float('nan'), True, 3601):
            with self.assertRaises(ValueError):
                self.build().execute(self.source, max_duration=value)
        self.assertEqual(self.events, [])

    def test_wrong_stage_is_not_persisted_as_success(self):
        class WrongEngine:
            def analyze(self, stage, audio):
                return StageResult('energy', (), 'bad adapter')
        report = AnalyzeTrack(Decoder(self.events), WrongEngine(), Repository(self.events)).execute(self.source)
        self.assertEqual(report.status, 'failed')
        self.assertEqual(report.stages, ())
