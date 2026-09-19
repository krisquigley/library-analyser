import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from music_analyzer.infrastructure.filesystem.inventory import LocalInventory
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository, APPLICATION_ID
from music_analyzer.application.use_cases.scan_library import ScanLibrary, ResolveTrack
from music_analyzer.application.dto.catalogue import ScanLimits


class CatalogueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / 'music'
        self.root.mkdir()
        self.db = self.base / 'analysis.sqlite'

    def scan(self, limits=ScanLimits()):
        return ScanLibrary(LocalInventory(), SQLiteAnalysisRepository(str(self.db))).execute(str(self.root), limits)

    def test_duplicate_move_change_missing_and_unicode(self):
        a = self.root / 'été.flac'
        a.write_bytes(b'encoding one')
        b = self.root / 'copy.mp3'
        b.write_bytes(a.read_bytes())
        result = self.scan()
        track = result.files[0].identity.track_id
        repo = SQLiteAnalysisRepository(str(self.db))
        self.assertEqual(len(repo.locations(track)), 2)
        a.rename(self.root / 'moved.flac')
        result = self.scan()
        self.assertIn(str(a), result.missing)
        self.assertEqual(len(repo.locations(track)), 2)
        b.write_bytes(b'another encoding')
        self.scan()
        self.assertEqual(repo.locations(track), (str(self.root / 'moved.flac'),))
        (self.root / 'moved.flac').unlink()
        self.scan()
        self.assertEqual(repo.locations(track), ())
        self.assertEqual(len(self.scan().files), 1)

    def test_bounds_symlinks_and_partial_does_not_mark_missing(self):
        (self.root / 'a.flac').write_bytes(b'a')
        self.scan()
        (self.root / 'a.flac').unlink()
        (self.root / 'large.mp3').write_bytes(b'large')
        (self.root / 'loop').symlink_to(self.root, target_is_directory=True)
        (self.root / 'link.flac').symlink_to(self.root / 'large.mp3')
        result = self.scan(ScanLimits(max_file_bytes=2))
        self.assertFalse(result.complete)
        self.assertFalse(result.missing)
        self.assertTrue(result.issues)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('SELECT available FROM locations').fetchone(), (1,))
        self.assertLessEqual(len(self.scan(ScanLimits(max_entries=1)).files), 1)

    def test_lookup_rehashes_not_just_stat(self):
        f = self.root / 'a.flac'
        f.write_bytes(b'a')
        track = self.scan().files[0].identity.track_id
        f.write_bytes(b'b')
        with self.assertRaisesRegex(ValueError, 'scan'):
            ResolveTrack(SQLiteAnalysisRepository(str(self.db)), LocalInventory()).execute(track)

    def test_v1_migration_preserves_stage_bytes(self):
        with sqlite3.connect(self.db) as db:
            db.executescript('CREATE TABLE runs(id TEXT PRIMARY KEY,location TEXT,status TEXT,detail TEXT,created_at TEXT); CREATE TABLE stages(run_id TEXT,stage TEXT,result TEXT,PRIMARY KEY(run_id,stage));')
            db.execute(f'PRAGMA application_id={APPLICATION_ID}')
            db.execute('PRAGMA user_version=1')
            db.execute("INSERT INTO runs VALUES('run','old','completed','','then')")
            db.execute("INSERT INTO stages VALUES('run','rhythm',?)", ('{"provenance":"unchanged Unicode é"}',))
        SQLiteAnalysisRepository(str(self.db))
        SQLiteAnalysisRepository(str(self.db))
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone(), (4,))
            self.assertEqual(db.execute('SELECT result FROM stages').fetchone()[0], '{"provenance":"unchanged Unicode é"}')

    def test_malformed_v1_not_partially_migrated(self):
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE surprise(x)')
            db.execute(f'PRAGMA application_id={APPLICATION_ID}')
            db.execute('PRAGMA user_version=1')
        with self.assertRaises(Exception): SQLiteAnalysisRepository(str(self.db))
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone(), (1,))
            self.assertEqual(db.execute('SELECT name FROM sqlite_master').fetchall(), [('surprise',)])

    def test_per_file_read_error_does_not_abort_other_files(self):
        (self.root / 'bad.flac').write_bytes(b'bad')
        (self.root / 'good.flac').write_bytes(b'good')
        files = LocalInventory()
        original = files._read
        def read(path, maximum):
            if str(path).endswith('bad.flac'):
                raise PermissionError('Cannot read file; check permissions')
            return original(path, maximum)
        with patch.object(files, '_read', side_effect=read):
            result = files.inventory(str(self.root), ScanLimits())
        self.assertEqual(len(result.files), 1)
        self.assertEqual(len(result.issues), 1)
        self.assertIn('permissions', result.issues[0].detail)
        self.assertFalse(result.complete)

    def test_root_symlink_and_nonregular_audio_are_not_read(self):
        import os
        link = self.base / 'link'
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            LocalInventory().inventory(str(link), ScanLimits())
        os.mkfifo(self.root / 'pipe.flac')
        result = self.scan()
        self.assertFalse(result.complete)
        self.assertIn('regular', result.issues[0].detail)

    def test_failed_hash_reserves_remaining_read_budget(self):
        for name in ('one.flac', 'two.flac'):
            (self.root / name).write_bytes(b'x')
        files = LocalInventory()
        with patch.object(files, '_read', side_effect=ValueError('grew during read')) as read:
            result = files.inventory(str(self.root), ScanLimits(max_file_bytes=10, max_total_bytes=10))
        self.assertEqual(read.call_count, 1)
        self.assertFalse(result.complete)
