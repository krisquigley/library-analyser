from contextlib import closing
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from music_analyzer.application.dto.analysis import AudioSource, StageResult
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository
from music_analyzer.infrastructure.filesystem.inventory import LocalInventory
from music_analyzer.application.use_cases.scan_library import ScanLibrary
from music_analyzer.application.use_cases.review import ReviewTracks


class ReviewRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.path = self.root/'analysis.db'
        self.repo = SQLiteAnalysisRepository(str(self.path))
        (self.root/'音.flac').write_bytes(b'fake')
        self.track = ScanLibrary(LocalInventory(), self.repo).execute(str(self.root)).files[0].identity.track_id

    def test_identity_mapping_override_reanalysis_and_path_replacement(self):
        first = self.repo.start(AudioSource(str(self.root/'音.flac'), self.track))
        stage = StageResult('bpm', (('fake', 'yes'),), 'uncertain', (('bpm', 120.),), raw_predictions=(((.3,),),))
        self.repo.save_stage(first, stage); self.repo.finish(first, 'completed', '')
        review = ReviewTracks(self.repo); review.override(self.track, 'bpm', '121')
        read = self.repo.read_track(self.track)
        self.assertEqual(read.run.stages, (stage,))
        second = self.repo.start(AudioSource('moved', self.track)); self.repo.finish(second, 'failed', 'fixture')
        reopened = SQLiteAnalysisRepository(str(self.path))
        self.assertEqual(reopened.read_track(self.track).run.run_id, second)
        self.assertEqual(dict(ReviewTracks(reopened).show(self.track).effective)['bpm'], '121')
        unrelated = self.repo.start(AudioSource(str(self.root/'音.flac')))
        self.repo.finish(unrelated, 'completed', '')
        self.assertEqual(reopened.read_track(self.track).run.run_id, second)
        review.override(self.track, 'bpm', None)
        self.assertFalse(reopened.read_track(self.track).overrides)

    def test_v3_transactional_migration_preserves_rows_and_failure_rolls_back(self):
        run = self.repo.start(AudioSource('legacy'))
        self.repo.save_stage(run, StageResult('bpm', (), 'legacy'))
        with closing(sqlite3.connect(self.path)) as db, db:
            before = db.execute('SELECT * FROM stages').fetchall()
            db.execute('DROP TABLE run_tracks'); db.execute('DROP TABLE overrides'); db.execute('PRAGMA user_version=3')
        original = SQLiteAnalysisRepository._validate
        def fail(repo, db, version=4):
            if version == 4: raise ValueError('injected migration failure')
            return original(repo, db, version)
        with patch.object(SQLiteAnalysisRepository, '_validate', fail):
            with self.assertRaises(ValueError): SQLiteAnalysisRepository(str(self.path))
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 3)
            self.assertEqual(db.execute('SELECT * FROM stages').fetchall(), before)
            self.assertFalse(db.execute("SELECT name FROM sqlite_master WHERE name='overrides'").fetchall())
        SQLiteAnalysisRepository(str(self.path))
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute('SELECT * FROM stages').fetchall(), before)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 4)

    def test_bad_payload_fails_honestly_and_legacy_raw_optional(self):
        run = self.repo.start(AudioSource('fake', self.track))
        self.repo.save_stage(run, StageResult('bpm', (), 'old'))
        with closing(sqlite3.connect(self.path)) as db, db:
            payload = json.loads(db.execute('SELECT result FROM stages').fetchone()[0]); payload.pop('raw_predictions')
            db.execute('UPDATE stages SET result=?', (json.dumps(payload),))
        self.assertEqual(self.repo.read_track(self.track).run.stages[0].raw_predictions, ())
        with closing(sqlite3.connect(self.path)) as db, db: db.execute("UPDATE stages SET result='not json'")
        with self.assertRaisesRegex(Exception, 'stored stage'): self.repo.read_track(self.track)

    def test_nonfinite_or_malformed_stored_values_are_rejected(self):
        run = self.repo.start(AudioSource('fake', self.track))
        self.repo.save_stage(run, StageResult('bpm', (), 'old'))
        for changes in ({'values': [['bpm', float('nan')]]}, {'provenance': 'bad'},
                        {'windows': [{'start': 0, 'end': 1, 'scores': [float('inf')]}]}):
            payload = {'stage': 'bpm', 'provenance': [], 'uncertainty': 'old', **changes}
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute('UPDATE stages SET result=?', (json.dumps(payload),))
            with self.assertRaisesRegex(Exception, 'stored stage'): self.repo.read_track(self.track)

    def test_use_case_reanalysis_keeps_manual_annotation_and_batch_link(self):
        from contextlib import contextmanager
        from music_analyzer.application.dto.analysis import DecodedAudio
        from music_analyzer.application.use_cases.analyze_track import AnalyzeTrack
        from music_analyzer.infrastructure.persistence.batch import SQLiteBatchQueue
        from music_analyzer.application.ports.batch import BatchJob
        class Decoder:
            @contextmanager
            def decode(self, source, maximum): yield DecodedAudio('fake', 10, 44100)
        class Engine:
            def analyze(self, stage, audio): return StageResult(stage, (('fixture', 'no inference'),), 'unvalidated')
        review = ReviewTracks(self.repo)
        review.override(self.track, 'key', 'Manual é')
        worker = AnalyzeTrack(Decoder(), Engine(), self.repo)
        first = worker.execute(AudioSource('fake', self.track))
        second = worker.execute(AudioSource('fake', self.track))
        self.assertNotEqual(first.run_id, second.run_id)
        self.assertEqual(review.show(self.track).track.run.run_id, second.run_id)
        self.assertEqual(dict(review.show(self.track).effective)['key'], 'Manual é')
        queue = SQLiteBatchQueue(str(self.path))
        queue.put_job(BatchJob(self.track, 'fixture', 'running', 1))
        batch = AnalyzeTrack(Decoder(), Engine(), queue).execute(AudioSource('fake', self.track))
        self.assertEqual(review.show(self.track).track.run.run_id, batch.run_id)
        self.assertEqual(dict(review.show(self.track).effective)['key'], 'Manual é')
