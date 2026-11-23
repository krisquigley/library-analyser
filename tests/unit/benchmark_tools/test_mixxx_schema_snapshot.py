"""Issue #133: the tool that turns Mixxx's public res/schema.xml into the pinned schema the export creates."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tools.mixxx_schema_snapshot import SchemaSnapshotError, main, schema_snapshot

SYNTHETIC_SCHEMA_XML = '''<!DOCTYPE schema>
<schema>
  <revision version="1">
    <description>Base tables.</description>
    <sql>CREATE TABLE IF NOT EXISTS settings (name TEXT UNIQUE NOT NULL, value TEXT);
         CREATE TABLE IF NOT EXISTS library (id INTEGER PRIMARY KEY AUTOINCREMENT, bpm FLOAT);</sql>
  </revision>
  <revision version="2" min_compatible="1">
    <description>Add key.</description>
    <sql>ALTER TABLE library ADD COLUMN key varchar(8) DEFAULT '';</sql>
    <sql></sql>
  </revision>
</schema>
'''


class SchemaSnapshotTests(unittest.TestCase):
    def test_the_revisions_are_replayed_and_the_final_schema_written_with_its_provenance(self):
        snapshot = schema_snapshot(SYNTHETIC_SCHEMA_XML, source='mixxxdj/mixxx 9.9.9 (commit abc) res/schema.xml')
        self.assertEqual(2, snapshot.revision)
        self.assertEqual(1, snapshot.min_compatible)
        self.assertIn('-- Source: mixxxdj/mixxx 9.9.9 (commit abc) res/schema.xml', snapshot.sql)
        self.assertIn('-- Schema revision: 2 (min_compatible 1)', snapshot.sql)
        database = sqlite3.connect(':memory:')
        database.executescript(snapshot.sql)
        self.assertEqual(['id', 'bpm', 'key'], [column[1] for column in database.execute('PRAGMA table_info(library)')])
        self.assertEqual(['settings', 'library'], [row[0] for row in database.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY rowid")])

    def test_a_document_without_revisions_or_with_failing_sql_is_refused(self):
        for document in ['<schema/>', '<schema><revision version="1"><sql>CREATE TABL x;</sql></revision></schema>']:
            with self.subTest(document=document):
                with self.assertRaises(SchemaSnapshotError):
                    schema_snapshot(document, source='synthetic')

    def test_the_command_writes_a_new_file_and_refuses_an_existing_one(self):
        with tempfile.TemporaryDirectory() as temp:
            schema_xml, output = Path(temp) / 'schema.xml', Path(temp) / 'schema.sql'
            schema_xml.write_text(SYNTHETIC_SCHEMA_XML)
            self.assertEqual(0, main(['--schema-xml', str(schema_xml), '--source', 'synthetic', '--output', str(output)]))
            self.assertIn('CREATE TABLE', output.read_text())
            with self.assertRaises(SystemExit):
                main(['--schema-xml', str(schema_xml), '--source', 'synthetic', '--output', str(output)])


if __name__ == '__main__':
    unittest.main()
