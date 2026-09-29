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
                self.assertEqual(cli('analyze')[0], 0)
                self.assertEqual(cli('analyze', '--force', '--limit', '1')[0], 1)
                self.assertEqual(cli('analyze', '--retry-failed')[0], 1)
                failed = [j for j in cli('status')[1]['jobs'] if j['state'] == 'failed']
                self.assertEqual([j['attempts'] for j in failed], [2])

    def test_catalogue_track_selector_retries_only_named_failed_jobs_with_new_duration(self):
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
                build.return_value = ('old-recipe', lambda s, d: AnalysisReport('old-run', 'completed', ()))
                self.assertEqual(cli('analyze')[0], 0)
                first, second = [job['track_id'] for job in cli('status')[1]['jobs']]
                build.return_value = ('failed-recipe', lambda s, d: AnalysisReport('failed-run', 'failed', (), 'duration'))
                self.assertEqual(cli('analyze', '--force', '--limit', '1')[0], 1)
                durations = []
                def retry(source, duration):
                    durations.append((source.location, duration))
                    return AnalysisReport('retry-run', 'completed', ())
                selected_file = Path(tmp) / 'selected.txt'
                selected_file.write_text(f'# retry batch\n{second}\n')
                build.return_value = ('duration-4757-recipe', retry)
                code, report = cli('analyze', '--retry-failed', '--catalogue-track', first, '--catalogue-tracks-file', str(selected_file), '--max-duration', '4757')
                self.assertEqual(code, 0)
                self.assertEqual(len(durations), 1)
                jobs = {job['track_id']: job for job in report['jobs']}
                self.assertEqual(jobs[first]['fingerprint'], 'duration-4757-recipe')
                self.assertEqual(jobs[second]['fingerprint'], 'old-recipe')
                self.assertEqual(durations[0][1], 4757)
                build.return_value = ('default-recipe', lambda s, d: self.fail('completed catalogue jobs are not implicitly stale'))
                self.assertEqual(cli('analyze')[0], 0)

    def test_catalogue_tracks_file_and_conflicting_args_are_decoded_by_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            track_file = Path(tmp) / 'tracks.txt'
            track_file.write_text('\n# comment\ntrack-a\ntrack-b\n')
            for args in (
                ['analyze', '--catalogue-track', 'track-a'],
                ['analyze', '--catalogue-track', 'track-a', '--retry-failed', '--limit', '1'],
                ['analyze', '--catalogue-tracks-file', str(track_file), '--retry-failed', '--force'],
                ['analyze', '--catalogue-track', 'track-a', '--retry-failed', '--track', 'track-a'],
            ):
                with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    main(args)

    def test_max_duration_cli_bound_is_5000_seconds(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(['analyze', '--file', 'fixture', '--max-duration', '5001'])
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(output):
            code = main(['analyze', '--file', str(Path(tmp) / 'missing.flac'), '--database', str(Path(tmp) / 'analysis.sqlite'), '--max-duration', '5000', '--json'])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue())['status'], 'setup_failed')

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
