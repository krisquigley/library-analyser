"""Robustness contracts for synthetic-only outward fixture inspection."""
import importlib
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest

try:
    inspection = importlib.import_module('tools.explorer_fixture_inspection')
except ModuleNotFoundError as error:
    if error.name != 'tools.explorer_fixture_inspection':
        raise
    inspection = SimpleNamespace(inspect_fixture=lambda *a: {}, fingerprint_sqlite_files=lambda *a: {})


class FixtureInspectionRobustnessTests(unittest.TestCase):
    def test_missing_input_is_not_created_by_either_api(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'missing.sqlite'
            for operation in (inspection.inspect_fixture, inspection.fingerprint_sqlite_files):
                with self.subTest(operation=operation):
                    with self.assertRaises(FileNotFoundError):
                        operation(path)
                    self.assertFalse(path.exists())

    def test_invalid_fixture_error_does_not_disclose_path_or_database_text(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'private-title.sqlite'
            path.write_bytes(b'private fixture text, not SQLite')
            before = path.read_bytes()
            with self.assertRaises(ValueError) as caught:
                inspection.inspect_fixture(path)
            self.assertEqual(str(caught.exception), 'Invalid synthetic SQLite fixture')
            self.assertEqual(path.read_bytes(), before)

    def test_unrecognized_sqlite_schema_is_rejected_without_modification(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.sqlite'
            db = sqlite3.connect(path)
            try:
                db.execute('CREATE TABLE unrelated(value TEXT)')
                db.commit()
            finally:
                db.close()
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, '^Invalid synthetic SQLite fixture$'):
                inspection.inspect_fixture(path)
            self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
