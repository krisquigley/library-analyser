from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from music_analyzer.application.dto.analysis import AnalysisError, AudioSource, StageResult
from music_analyzer.application.dto.catalogue import Inventory, ScannedFile, TrackMetadata
from music_analyzer.domain.catalogue import FileIdentity
from music_analyzer.application.use_cases.scan_library import ScanLibrary
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository, APPLICATION_ID
from music_analyzer.infrastructure.persistence.explorer_readonly import ReadOnlyExplorerSQLiteRepository


class StaticInventory:
    def __init__(self, files):
        self._files = tuple(files)

    def inventory(self, root, limits):
        return Inventory(root, self._files, (), True)

    def matches(self, location, track_id):  # pragma: no cover - not used by these tests
        return False


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
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 6)
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
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 6)
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
            db.execute('DROP VIEW IF EXISTS active_locations')
            db.execute('DROP VIEW IF EXISTS active_tracks')
            db.execute('DROP TABLE IF EXISTS track_audio')
            db.execute('DROP TABLE track_metadata')
            db.execute('CREATE TABLE track_metadata(track_id TEXT PRIMARY KEY, common_json TEXT NOT NULL, tags_json TEXT NOT NULL, warnings_json TEXT NOT NULL)')
            db.execute('PRAGMA user_version=5')
            db.commit()
        with self.assertRaises(AnalysisError):
            SQLiteAnalysisRepository(str(self.path))

    def test_v5_migration_adds_duration_inventory_without_losing_existing_catalogue_state(self):
        track_id = 'sha256:' + 'b' * 64
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript(f'''
                PRAGMA application_id={APPLICATION_ID};
                PRAGMA user_version=5;
                CREATE TABLE runs(id TEXT PRIMARY KEY, location TEXT NOT NULL, status TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE stages(run_id TEXT NOT NULL, stage TEXT NOT NULL, result TEXT NOT NULL, PRIMARY KEY(run_id,stage));
                CREATE TABLE tracks(id TEXT PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, size INTEGER NOT NULL);
                CREATE TABLE locations(path TEXT PRIMARY KEY, track_id TEXT NOT NULL, mtime_ns INTEGER NOT NULL, format TEXT NOT NULL, available INTEGER NOT NULL);
                CREATE TABLE scan_roots(root TEXT NOT NULL, path TEXT NOT NULL, PRIMARY KEY(root,path));
                CREATE TABLE batch_jobs(track_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, state TEXT NOT NULL, attempts INTEGER NOT NULL, run_id TEXT, detail TEXT NOT NULL);
                CREATE TABLE run_tracks(run_id TEXT PRIMARY KEY, track_id TEXT NOT NULL);
                CREATE TABLE overrides(track_id TEXT NOT NULL, field TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY(track_id,field));
                CREATE TABLE track_metadata(track_id TEXT PRIMARY KEY REFERENCES tracks(id), common_json TEXT NOT NULL, tags_json TEXT NOT NULL, warnings_json TEXT NOT NULL);
            ''')
            db.execute('INSERT INTO tracks VALUES(?,?,?)', (track_id, 'b' * 64, 123))
            db.execute('INSERT INTO locations VALUES(?,?,?,?,?)', ('/music/old.flac', track_id, 7, 'flac', 1))
            db.execute('INSERT INTO scan_roots VALUES(?,?)', ('/music', '/music/old.flac'))
            db.execute('INSERT INTO runs VALUES(?,?,?,?,?)', ('run', '/music/old.flac', 'completed', 'ok', 'then'))
            db.execute('INSERT INTO run_tracks VALUES(?,?)', ('run', track_id))
            db.execute('INSERT INTO overrides VALUES(?,?,?)', (track_id, 'key', 'C'))
            db.execute('INSERT INTO batch_jobs VALUES(?,?,?,?,?,?)', (track_id, 'fp', 'failed', 2, 'run', 'keep'))
            db.execute('INSERT INTO track_metadata VALUES(?,?,?,?)', (track_id, '[["title","Old"]]', '[]', '[]'))
            db.commit()

        SQLiteAnalysisRepository(str(self.path))

        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 6)
            self.assertEqual(db.execute('SELECT id,sha256,size FROM tracks').fetchone(), (track_id, 'b' * 64, 123))
            self.assertEqual(db.execute('SELECT path,track_id,available FROM locations').fetchone(), ('/music/old.flac', track_id, 1))
            self.assertEqual(db.execute('SELECT state,attempts,run_id,detail FROM batch_jobs').fetchone(), ('failed', 2, 'run', 'keep'))
            self.assertEqual(db.execute('SELECT field,value FROM overrides').fetchone(), ('key', 'C'))
            self.assertEqual(db.execute('SELECT duration_seconds,duration_source,status,reason FROM track_audio WHERE track_id=?', (track_id,)).fetchone(), (None, '', 'unknown', 'duration unverified; excluded from active library until mutagen/ffprobe verifies duration; rescan audio metadata'))
            self.assertEqual(db.execute('SELECT count(*) FROM active_tracks').fetchone()[0], 0)

    def test_register_backfills_existing_track_duration_eligibility_without_changing_identity(self):
        repository = SQLiteAnalysisRepository(str(self.path))
        identity = FileIdentity('c' * 64, 123)
        repository.register(Inventory('/music', (ScannedFile('/music/song.flac', identity, 1, 'flac', TrackMetadata(duration_seconds=None, duration_source='mutagen')),), (), True))
        repository.register(Inventory('/music', (ScannedFile('/music/song.flac', identity, 1, 'flac', TrackMetadata(duration_seconds=1200.0, duration_source='mutagen')),), (), True))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM tracks').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT duration_seconds,duration_source,status,reason FROM track_audio WHERE track_id=?', (identity.track_id,)).fetchone(), (1200.0, 'mutagen', 'eligible', ''))
            self.assertEqual(db.execute('SELECT id FROM active_tracks').fetchone(), (identity.track_id,))

    def test_register_marks_long_and_unknown_tracks_inactive_but_preserves_locations(self):
        repository = SQLiteAnalysisRepository(str(self.path))
        long_id = FileIdentity('d' * 64, 123)
        unknown_id = FileIdentity('e' * 64, 123)
        repository.register(Inventory('/music', (
            ScannedFile('/music/long.flac', long_id, 1, 'flac', TrackMetadata(duration_seconds=1200.001, duration_source='ffprobe')),
            ScannedFile('/music/unknown.flac', unknown_id, 1, 'flac', TrackMetadata(warnings=('duration unavailable; excluded from active library',))),
        ), (), True))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM locations').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT status,reason FROM track_audio WHERE track_id=?', (long_id.track_id,)).fetchone(), ('excluded', 'duration 1200.001s >1200.0s; excluded from active library; rescan metadata or choose a shorter file'))
            self.assertEqual(db.execute('SELECT status,reason FROM track_audio WHERE track_id=?', (unknown_id.track_id,)).fetchone(), ('unknown', 'duration unverified; excluded from active library until mutagen/ffprobe verifies duration; rescan audio metadata'))
            self.assertEqual(db.execute('SELECT count(*) FROM active_locations').fetchone()[0], 0)

    def test_register_fails_closed_for_numeric_blank_source_and_zero_duration(self):
        repository = SQLiteAnalysisRepository(str(self.path))
        blank_id = FileIdentity('1' * 64, 123)
        zero_id = FileIdentity('2' * 64, 123)

        repository.register(Inventory('/music', (
            ScannedFile('/music/blank.flac', blank_id, 1, 'flac', TrackMetadata(duration_seconds=119.0, duration_source='')),
            ScannedFile('/music/zero.flac', zero_id, 1, 'flac', TrackMetadata(duration_seconds=0.0, duration_source='mutagen')),
        ), (), True))

        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT duration_seconds,duration_source,status FROM track_audio WHERE track_id=?', (blank_id.track_id,)).fetchone(), (119.0, '', 'unknown'))
            self.assertEqual(db.execute('SELECT duration_seconds,duration_source,status FROM track_audio WHERE track_id=?', (zero_id.track_id,)).fetchone(), (0.0, 'mutagen', 'excluded'))
            self.assertEqual(db.execute('SELECT count(*) FROM active_tracks').fetchone()[0], 0)

    def test_register_normalizes_single_trusted_nonfinite_duration_before_sqlite_insert(self):
        for value in (float('nan'), float('inf'), float('-inf')):
            with self.subTest(value=value):
                self.path.unlink(missing_ok=True)
                repository = SQLiteAnalysisRepository(str(self.path))
                identity = FileIdentity('7' * 64, 123)

                repository.register(Inventory('/music', (
                    ScannedFile('/music/nonfinite.flac', identity, 1, 'flac', TrackMetadata(duration_seconds=value, duration_source='mutagen')),
                ), (), True))
                SQLiteAnalysisRepository(str(self.path))

                with closing(sqlite3.connect(self.path)) as db:
                    self.assertEqual(
                        db.execute('SELECT duration_seconds,duration_source,status,reason FROM track_audio WHERE track_id=?', (identity.track_id,)).fetchone(),
                        (None, 'mutagen', 'unknown', 'duration unverified; excluded from active library until mutagen/ffprobe verifies duration; rescan audio metadata'),
                    )
                    self.assertEqual(db.execute('SELECT count(*) FROM active_tracks').fetchone()[0], 0)

    def test_duplicate_same_identity_coalesces_trusted_duration_regardless_scan_order(self):
        identity = FileIdentity('3' * 64, 123)
        for files in (
            (
                ScannedFile('/music/trusted.flac', identity, 1, 'flac', TrackMetadata(duration_seconds=300.0, duration_source='mutagen')),
                ScannedFile('/music/transient-failure.flac', identity, 1, 'flac', TrackMetadata(duration_seconds=None, duration_source='')),
            ),
            (
                ScannedFile('/music/transient-failure.flac', identity, 1, 'flac', TrackMetadata(duration_seconds=None, duration_source='')),
                ScannedFile('/music/trusted.flac', identity, 1, 'flac', TrackMetadata(duration_seconds=300.0, duration_source='mutagen')),
            ),
        ):
            self.path.unlink(missing_ok=True)
            repository = SQLiteAnalysisRepository(str(self.path))
            repository.register(Inventory('/music', files, (), True))
            with closing(sqlite3.connect(self.path)) as db:
                self.assertEqual(db.execute('SELECT duration_seconds,duration_source,status,reason FROM track_audio WHERE track_id=?', (identity.track_id,)).fetchone(), (300.0, 'mutagen', 'eligible', ''))
                self.assertEqual(db.execute('SELECT count(*) FROM locations WHERE track_id=?', (identity.track_id,)).fetchone()[0], 2)

    def test_scan_library_rescans_preserve_persisted_trusted_duration_across_roots_and_orders(self):
        identity = FileIdentity('8' * 64, 123)
        trusted = ScannedFile('/root-a/trusted.flac', identity, 1, 'flac', TrackMetadata(duration_seconds=300.0, duration_source='mutagen'))
        untrusted = ScannedFile('/root-b/untrusted.flac', identity, 2, 'flac', TrackMetadata(duration_seconds=None, duration_source=''))

        for first, second, repeated in ((trusted, untrusted, untrusted), (untrusted, trusted, untrusted)):
            with self.subTest(order=(first.location, second.location, repeated.location)):
                self.path.unlink(missing_ok=True)

                ScanLibrary(StaticInventory((first,)), SQLiteAnalysisRepository(str(self.path))).execute('/root-a' if first is trusted else '/root-b')
                ScanLibrary(StaticInventory((second,)), SQLiteAnalysisRepository(str(self.path))).execute('/root-a' if second is trusted else '/root-b')
                ScanLibrary(StaticInventory((repeated,)), SQLiteAnalysisRepository(str(self.path))).execute('/root-b')

                with closing(sqlite3.connect(self.path)) as db:
                    self.assertEqual(
                        db.execute('SELECT duration_seconds,duration_source,status,reason FROM track_audio WHERE track_id=?', (identity.track_id,)).fetchone(),
                        (300.0, 'mutagen', 'eligible', ''),
                    )
                    self.assertEqual(
                        tuple(row[0] for row in db.execute('SELECT path FROM active_locations WHERE track_id=? ORDER BY path', (identity.track_id,))),
                        ('/root-a/trusted.flac', '/root-b/untrusted.flac'),
                    )
                self.assertEqual(tuple(SQLiteAnalysisRepository(str(self.path)).track_ids()), (identity.track_id,))
                self.assertEqual(ReadOnlyExplorerSQLiteRepository(str(self.path)).track_ids(), (identity.track_id,))

    def test_migrated_catalogue_becomes_batch_and_explorer_active_after_trusted_rescan(self):
        identity = FileIdentity('0' * 64, 123)
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript(f'''
                PRAGMA application_id={APPLICATION_ID};
                PRAGMA user_version=5;
                CREATE TABLE runs(id TEXT PRIMARY KEY, location TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('running','completed','failed','interrupted')), detail TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE stages(run_id TEXT NOT NULL REFERENCES runs(id), stage TEXT NOT NULL, result TEXT NOT NULL, PRIMARY KEY(run_id,stage));
                CREATE TABLE tracks(id TEXT PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, size INTEGER NOT NULL);
                CREATE TABLE locations(path TEXT PRIMARY KEY, track_id TEXT NOT NULL REFERENCES tracks(id), mtime_ns INTEGER NOT NULL, format TEXT NOT NULL, available INTEGER NOT NULL CHECK(available IN (0,1)));
                CREATE TABLE scan_roots(root TEXT NOT NULL, path TEXT NOT NULL REFERENCES locations(path), PRIMARY KEY(root,path));
                CREATE TABLE batch_jobs(track_id TEXT PRIMARY KEY REFERENCES tracks(id), fingerprint TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('pending','running','completed','failed')), attempts INTEGER NOT NULL CHECK(attempts >= 0), run_id TEXT, detail TEXT NOT NULL);
                CREATE TABLE run_tracks(run_id TEXT PRIMARY KEY REFERENCES runs(id), track_id TEXT NOT NULL REFERENCES tracks(id));
                CREATE TABLE overrides(track_id TEXT NOT NULL REFERENCES tracks(id), field TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY(track_id,field));
                CREATE TABLE track_metadata(track_id TEXT PRIMARY KEY REFERENCES tracks(id), common_json TEXT NOT NULL, tags_json TEXT NOT NULL, warnings_json TEXT NOT NULL);
            ''')
            db.execute('INSERT INTO tracks VALUES(?,?,?)', (identity.track_id, identity.sha256, identity.size))
            db.execute('INSERT INTO locations VALUES(?,?,?,?,?)', ('/root-a/trusted.flac', identity.track_id, 1, 'flac', 1))
            db.execute('INSERT INTO scan_roots VALUES(?,?)', ('/root-a', '/root-a/trusted.flac'))
            db.execute('INSERT INTO track_metadata VALUES(?,?,?,?)', (identity.track_id, '[]', '[]', '[]'))
            db.commit()

        SQLiteAnalysisRepository(str(self.path))
        trusted = ScannedFile('/root-a/trusted.flac', identity, 1, 'flac', TrackMetadata(duration_seconds=300.0, duration_source='mutagen'))
        untrusted = ScannedFile('/root-b/untrusted.flac', identity, 2, 'flac', TrackMetadata(duration_seconds=None, duration_source=''))
        ScanLibrary(StaticInventory((trusted,)), SQLiteAnalysisRepository(str(self.path))).execute('/root-a')
        ScanLibrary(StaticInventory((untrusted,)), SQLiteAnalysisRepository(str(self.path))).execute('/root-b')

        self.assertEqual(tuple(SQLiteAnalysisRepository(str(self.path)).track_ids()), (identity.track_id,))
        self.assertEqual(ReadOnlyExplorerSQLiteRepository(str(self.path)).track_ids(), (identity.track_id,))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM active_locations WHERE track_id=?', (identity.track_id,)).fetchone(), (2,))

    def test_register_rejects_persisted_trusted_duration_conflicts_without_touching_history_or_jobs(self):
        repository = SQLiteAnalysisRepository(str(self.path))
        identity = FileIdentity('9' * 64, 123)
        repository.register(Inventory('/root-a', (
            ScannedFile('/root-a/trusted.flac', identity, 1, 'flac', TrackMetadata(duration_seconds=300.0, duration_source='mutagen')),
        ), (), True))
        run = repository.start(AudioSource('/root-a/trusted.flac', identity.track_id))
        repository.finish(run, 'completed', 'keep')
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('INSERT INTO batch_jobs VALUES(?,?,?,?,?,?)', (identity.track_id, 'fp', 'failed', 2, run, 'keep'))
            db.commit()

        for incoming in (1300.0, 0.0, float('nan')):
            with self.subTest(incoming=incoming):
                before = self.path.read_bytes()
                with self.assertRaisesRegex(AnalysisError, 'Conflicting trusted duration'):
                    SQLiteAnalysisRepository(str(self.path)).register(Inventory('/root-b', (
                        ScannedFile('/root-b/conflict.flac', identity, 2, 'flac', TrackMetadata(duration_seconds=incoming, duration_source='ffprobe')),
                    ), (), True))
                self.assertEqual(self.path.read_bytes(), before)
                with closing(sqlite3.connect(self.path)) as db:
                    self.assertEqual(db.execute('SELECT status,detail FROM runs WHERE id=?', (run,)).fetchone(), ('completed', 'keep'))
                    self.assertEqual(db.execute('SELECT state,attempts,run_id,detail FROM batch_jobs WHERE track_id=?', (identity.track_id,)).fetchone(), ('failed', 2, run, 'keep'))
                    self.assertFalse(db.execute("SELECT 1 FROM locations WHERE path='/root-b/conflict.flac'").fetchone())

    def test_register_rejects_conflicting_trusted_duplicate_durations(self):
        repository = SQLiteAnalysisRepository(str(self.path))
        identity = FileIdentity('4' * 64, 123)

        with self.assertRaisesRegex(AnalysisError, 'Conflicting trusted duration'):
            repository.register(Inventory('/music', (
                ScannedFile('/music/one.flac', identity, 1, 'flac', TrackMetadata(duration_seconds=10.0, duration_source='mutagen')),
                ScannedFile('/music/two.flac', identity, 1, 'flac', TrackMetadata(duration_seconds=11.0, duration_source='ffprobe')),
            ), (), True))

        with closing(sqlite3.connect(self.path)) as db:
            self.assertFalse(db.execute('SELECT 1 FROM track_audio').fetchone())

    def test_register_rejects_conflicting_trusted_duplicate_duration_even_when_one_is_too_long(self):
        repository = SQLiteAnalysisRepository(str(self.path))
        identity = FileIdentity('5' * 64, 123)

        with self.assertRaisesRegex(AnalysisError, 'Conflicting trusted duration'):
            repository.register(Inventory('/music', (
                ScannedFile('/music/short.flac', identity, 1, 'flac', TrackMetadata(duration_seconds=300.0, duration_source='mutagen')),
                ScannedFile('/music/long.flac', identity, 1, 'flac', TrackMetadata(duration_seconds=1300.0, duration_source='ffprobe')),
            ), (), True))

        with closing(sqlite3.connect(self.path)) as db:
            self.assertFalse(db.execute('SELECT 1 FROM track_audio').fetchone())
            self.assertFalse(db.execute('SELECT 1 FROM locations').fetchone())

    def test_register_rejects_trusted_duplicate_duration_when_one_value_is_invalid_in_any_order(self):
        identity = FileIdentity('6' * 64, 123)
        invalid_values = (0.0, float('nan'), float('inf'), float('-inf'), 1300.0)
        for invalid in invalid_values:
            for files in (
                (
                    ScannedFile('/music/valid.flac', identity, 1, 'flac', TrackMetadata(duration_seconds=300.0, duration_source='mutagen')),
                    ScannedFile('/music/invalid.flac', identity, 1, 'flac', TrackMetadata(duration_seconds=invalid, duration_source='ffprobe')),
                ),
                (
                    ScannedFile('/music/invalid.flac', identity, 1, 'flac', TrackMetadata(duration_seconds=invalid, duration_source='ffprobe')),
                    ScannedFile('/music/valid.flac', identity, 1, 'flac', TrackMetadata(duration_seconds=300.0, duration_source='mutagen')),
                ),
            ):
                with self.subTest(invalid=invalid, order=tuple(file.location for file in files)):
                    self.path.unlink(missing_ok=True)
                    repository = SQLiteAnalysisRepository(str(self.path))

                    with self.assertRaisesRegex(AnalysisError, 'Conflicting trusted duration'):
                        repository.register(Inventory('/music', files, (), True))

                    with closing(sqlite3.connect(self.path)) as db:
                        self.assertFalse(db.execute('SELECT 1 FROM track_audio').fetchone())
                        self.assertFalse(db.execute('SELECT 1 FROM locations').fetchone())
                        self.assertFalse(db.execute('SELECT 1 FROM track_metadata').fetchone())

    def test_register_rejects_duplicate_track_identity_race_before_audio_backfill(self):
        repository = SQLiteAnalysisRepository(str(self.path))
        first = ScannedFile('/music/one.flac', FileIdentity('f' * 64, 1), 1, 'flac', TrackMetadata(duration_seconds=60))
        duplicate = ScannedFile('/music/two.flac', FileIdentity('f' * 64, 2), 1, 'flac', TrackMetadata(duration_seconds=60))
        with self.assertRaises(AnalysisError):
            repository.register(Inventory('/music', (first, duplicate), (), True))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertFalse(db.execute('SELECT 1 FROM track_audio').fetchone())

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
