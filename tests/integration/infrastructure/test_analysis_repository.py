from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from music_analyzer.application.dto.analysis import AnalysisError, AudioSource, StageResult
from music_analyzer.application.dto.catalogue import Inventory, ScannedFile, TrackMetadata
from music_analyzer.domain.catalogue import FileIdentity
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository, APPLICATION_ID


class AnalysisRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'analysis.sqlite'

    def test_new_database_has_identity_version_and_durable_stage_provenance(self):
        repository = SQLiteAnalysisRepository(str(self.path))
        run = repository.start(AudioSource('/music/空 白.flac'))
        repository.save_stage(run, StageResult('bpm', (('algorithm', 'test-fake'),), 'not beat grid',
                                               (('bpm', 120.0),)))
        repository.finish(run, 'failed', 'key: unavailable')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('PRAGMA application_id').fetchone()[0], APPLICATION_ID)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 5)
            self.assertEqual(db.execute('SELECT location,status,detail FROM runs').fetchone(),
                             ('/music/空 白.flac', 'failed', 'key: unavailable'))
            stage = json.loads(db.execute('SELECT result FROM stages').fetchone()[0])
            self.assertEqual(stage['provenance'], [['algorithm', 'test-fake']])
            self.assertEqual(stage['values'], [['bpm', 120.0]])
        SQLiteAnalysisRepository(str(self.path))  # valid reopen, no destructive recovery


    def test_v4_migration_rebuilds_track_metadata_table_with_missing_primary_key(self):
        track_id = 'sha256:' + 'a' * 64
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript(f'''
                PRAGMA application_id={APPLICATION_ID};
                PRAGMA user_version=4;
                CREATE TABLE runs(id TEXT PRIMARY KEY, location TEXT NOT NULL, status TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE stages(run_id TEXT NOT NULL, stage TEXT NOT NULL, result TEXT NOT NULL, PRIMARY KEY(run_id,stage));
                CREATE TABLE tracks(id TEXT PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, size INTEGER NOT NULL);
                CREATE TABLE locations(path TEXT PRIMARY KEY, track_id TEXT NOT NULL, mtime_ns INTEGER NOT NULL, format TEXT NOT NULL, available INTEGER NOT NULL);
                CREATE TABLE scan_roots(root TEXT NOT NULL, path TEXT NOT NULL, PRIMARY KEY(root,path));
                CREATE TABLE batch_jobs(track_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, state TEXT NOT NULL, attempts INTEGER NOT NULL, run_id TEXT, detail TEXT NOT NULL);
                CREATE TABLE run_tracks(run_id TEXT PRIMARY KEY, track_id TEXT NOT NULL);
                CREATE TABLE overrides(track_id TEXT NOT NULL, field TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY(track_id,field));
                CREATE TABLE track_metadata(track_id TEXT NOT NULL, common_json TEXT NOT NULL, tags_json TEXT NOT NULL, warnings_json TEXT NOT NULL);
            ''')
            db.execute('INSERT INTO tracks VALUES(?,?,?)', (track_id, 'a' * 64, 123))
            db.execute(
                'INSERT INTO track_metadata VALUES(?,?,?,?)',
                (track_id, '[["title","Tagged Song"]]', '[["TIT2",["Tagged Song"]]]', '[]'),
            )
            db.commit()

        SQLiteAnalysisRepository(str(self.path))

        with closing(sqlite3.connect(self.path)) as db:
            table_info = tuple(db.execute('PRAGMA table_info(track_metadata)'))
            primary_key_columns = tuple(row[1] for row in sorted((row for row in table_info if row[5]), key=lambda row: row[5]))
            self.assertEqual(primary_key_columns, ('track_id',))
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 5)
            self.assertEqual(
                db.execute('SELECT common_json,tags_json,warnings_json FROM track_metadata WHERE track_id=?', (track_id,)).fetchone(),
                ('[["title","Tagged Song"]]', '[["TIT2",["Tagged Song"]]]', '[]'),
            )

    def test_v4_migration_rejects_duplicate_track_metadata_before_rebuilding_primary_key(self):
        track_id = 'sha256:' + 'a' * 64
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript(f'''
                PRAGMA application_id={APPLICATION_ID};
                PRAGMA user_version=4;
                CREATE TABLE runs(id TEXT PRIMARY KEY, location TEXT NOT NULL, status TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE stages(run_id TEXT NOT NULL, stage TEXT NOT NULL, result TEXT NOT NULL, PRIMARY KEY(run_id,stage));
                CREATE TABLE tracks(id TEXT PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, size INTEGER NOT NULL);
                CREATE TABLE locations(path TEXT PRIMARY KEY, track_id TEXT NOT NULL, mtime_ns INTEGER NOT NULL, format TEXT NOT NULL, available INTEGER NOT NULL);
                CREATE TABLE scan_roots(root TEXT NOT NULL, path TEXT NOT NULL, PRIMARY KEY(root,path));
                CREATE TABLE batch_jobs(track_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, state TEXT NOT NULL, attempts INTEGER NOT NULL, run_id TEXT, detail TEXT NOT NULL);
                CREATE TABLE run_tracks(run_id TEXT PRIMARY KEY, track_id TEXT NOT NULL);
                CREATE TABLE overrides(track_id TEXT NOT NULL, field TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY(track_id,field));
                CREATE TABLE track_metadata(track_id TEXT NOT NULL, common_json TEXT NOT NULL, tags_json TEXT NOT NULL, warnings_json TEXT NOT NULL);
            ''')
            db.execute('INSERT INTO tracks VALUES(?,?,?)', (track_id, 'a' * 64, 123))
            db.execute('INSERT INTO track_metadata VALUES(?,?,?,?)', (track_id, '[]', '[]', '[]'))
            db.execute('INSERT INTO track_metadata VALUES(?,?,?,?)', (track_id, '[["title","Duplicate"]]', '[]', '[]'))
            db.commit()

        with self.assertRaises(AnalysisError):
            SQLiteAnalysisRepository(str(self.path))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 4)

    def test_v5_rejects_track_metadata_without_required_foreign_key(self):
        repository = SQLiteAnalysisRepository(str(self.path))
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('DROP TABLE track_metadata')
            db.execute('CREATE TABLE track_metadata(track_id TEXT PRIMARY KEY, common_json TEXT NOT NULL, tags_json TEXT NOT NULL, warnings_json TEXT NOT NULL)')
            db.commit()
        with self.assertRaises(AnalysisError):
            SQLiteAnalysisRepository(str(self.path))

    def test_register_persists_embedded_track_metadata_without_migration_backfill_io(self):
        repository = SQLiteAnalysisRepository(str(self.path))
        metadata = TrackMetadata(
            common=(('title', 'Tagged Title'), ('artist', ('One', 'Two'))),
            tags=(('TITLE', ('Tagged Title',)), ('custom:rating', ('5',))),
            warnings=(('APIC: embedded artwork/binary metadata omitted'),),
        )
        inventory = Inventory('/music', (ScannedFile('/music/song.flac', FileIdentity('a' * 64, 123), 1, 'flac', metadata),), (), True)
        repository.register(inventory)
        track = repository.read_track('sha256:' + 'a' * 64)
        self.assertEqual(track.metadata, metadata)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM track_metadata').fetchone()[0], 1)

    def test_rejects_foreign_empty_identified_and_future_databases_without_modification(self):
        for setup in ('CREATE TABLE library (id INTEGER)', 'PRAGMA application_id=123',
                      f'PRAGMA application_id={APPLICATION_ID}; PRAGMA user_version=999',
                      'PRAGMA user_version=1',
                      f'PRAGMA application_id={APPLICATION_ID}; PRAGMA user_version=1'):
            with self.subTest(setup=setup):
                self.path.unlink(missing_ok=True)
                with closing(sqlite3.connect(self.path)) as db:
                    db.executescript(setup)
                before = self.path.read_bytes()
                with self.assertRaises(AnalysisError):
                    SQLiteAnalysisRepository(str(self.path))
                self.assertEqual(self.path.read_bytes(), before)

    def test_rejects_symlink_and_mixxx_named_empty_database(self):
        for name in ('mixxx.sqlite', 'Mixxx.db'):
            path = Path(self.temp.name) / name
            path.touch()
            with self.assertRaises(AnalysisError):
                SQLiteAnalysisRepository(str(path))
            self.assertEqual(path.read_bytes(), b'')
        self.path.touch()
        link = Path(self.temp.name) / 'link.sqlite'
        link.symlink_to(self.path)
        with self.assertRaises(AnalysisError):
            SQLiteAnalysisRepository(str(link))

    def test_runs_are_distinct_and_completed_run_cannot_be_overwritten(self):
        repository = SQLiteAnalysisRepository(str(self.path))
        one = repository.start(AudioSource('same.flac'))
        two = repository.start(AudioSource('same.flac'))
        self.assertNotEqual(one, two)
        repository.save_stage(one, StageResult('key', (), 'uncertain'))
        with self.assertRaises(AnalysisError):
            repository.save_stage(one, StageResult('key', (), 'replacement'))
        repository.finish(one, 'completed', '')
        with self.assertRaises(AnalysisError):
            repository.save_stage(one, StageResult('bpm', (), 'late'))
        with self.assertRaises(AnalysisError):
            repository.finish('missing', 'completed', '')

    def test_raw_prediction_matrices_survive_reopen(self):
        repository = SQLiteAnalysisRepository(str(self.path))
        run = repository.start(AudioSource('fake'))
        repository.save_stage(run, StageResult('mood', (), 'raw', raw_predictions=(((.1, .9), (.3, .7)),)))
        repository.finish(run, 'completed', '')
        SQLiteAnalysisRepository(str(self.path))
        with closing(sqlite3.connect(self.path)) as db:
            stage = json.loads(db.execute('SELECT result FROM stages').fetchone()[0])
        self.assertEqual(stage['raw_predictions'], [[[.1, .9], [.3, .7]]])
