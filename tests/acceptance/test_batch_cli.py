import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from music_analyzer.application.dto.analysis import AnalysisReport
from music_analyzer.frameworks.cli.main import main


class BatchCLITests(unittest.TestCase):
    def test_catalogue_dispatch_status_skip_force_and_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'root'; root.mkdir()
            (root / 'a.flac').write_bytes(b'a'); (root / 'b.flac').write_bytes(b'b')
            db = str(Path(tmp) / 'analysis.sqlite')
            def cli(*args):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    code = main([*args, '--database', db, '--json'])
                return code, json.loads(output.getvalue())
            self.assertEqual(cli('scan', str(root))[0], 0)
            with patch('music_analyzer.frameworks.cli.main.build_batch_worker') as build:
                calls = []
                def analyze(source, duration):
                    calls.append(source.location)
                    return AnalysisReport('fake-run', 'completed', ())
                build.return_value = ('fake-verified-recipe', analyze)
                code, report = cli('analyze', '--limit', '1')
                self.assertEqual(code, 0); self.assertEqual(report['counts']['completed'], 1)
                self.assertEqual(cli('analyze')[0], 0)
                self.assertEqual(cli('analyze')[0], 0); self.assertEqual(len(calls), 2)
                self.assertEqual(cli('analyze', '--force', '--limit', '1')[0], 0)
                self.assertEqual(len(calls), 3)
                code, report = cli('status')
                self.assertEqual(code, 0); self.assertEqual(report['counts']['completed'], 2)
                build.return_value = ('changed-recipe', lambda s, d: AnalysisReport('failed-run', 'failed', (), 'fake corrupt'))
                self.assertEqual(cli('analyze')[0], 1)
                self.assertEqual(cli('analyze', '--retry-failed')[0], 1)
                self.assertTrue(all(j['attempts'] == 2 for j in cli('status')[1]['jobs']))

    def test_batch_options_rejected_for_explicit_source(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(['analyze', '--file', 'fixture', '--force'])

    def test_fake_engine_interrupt_checkpoint_and_resume(self):
        from music_analyzer.application.use_cases.analyze_track import AnalyzeTrack
        from music_analyzer.application.dto.analysis import DecodedAudio, StageResult
        from music_analyzer.infrastructure.persistence.batch import SQLiteBatchQueue
        class Decoder:
            def decode(self, source, duration):
                return contextlib.nullcontext(DecodedAudio(source.location, 1, 44100))
        class Engine:
            interrupted = False
            def analyze(self, stage, audio):
                if stage == 'key' and not self.interrupted:
                    self.interrupted = True
                    raise KeyboardInterrupt()
                return StageResult(stage, (('engine', 'fake'),), 'No inference')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'root'; root.mkdir()
            (root / 'fixture.flac').write_bytes(b'not audio')
            db = str(Path(tmp) / 'db')
            engine = Engine()
            def worker(settings, duration):
                return 'fake', AnalyzeTrack(Decoder(), engine, SQLiteBatchQueue(db)).execute
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(['scan', str(root), '--database', db]), 0)
                with patch('music_analyzer.frameworks.cli.main.build_batch_worker', worker):
                    self.assertEqual(main(['analyze', '--database', db]), 130)
                    job = SQLiteBatchQueue(db).status()[0]
                    self.assertEqual(job.state, 'pending')
                    self.assertIsNotNone(job.run_id)
                    self.assertEqual(main(['analyze', '--database', db]), 0)
                    self.assertEqual(SQLiteBatchQueue(db).status()[0].attempts, 2)
