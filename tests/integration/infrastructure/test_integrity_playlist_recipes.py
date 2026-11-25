"""Issue #139: the integrity diagnostic audits every stored playlist recipe row from schema v11 on."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from music_analyzer.application.use_cases.check_integrity import CheckIntegrity
from music_analyzer.infrastructure.persistence.integrity import SQLiteIntegrityScanner
from tests.integration.infrastructure.integrity_d1_public_fixture import PUBLIC_TRACK_IDS, create_public_core_database


def _recipe(**changes):
    return {'format': 'playlist-recipe', 'version': 2, 'start_track_id': PUBLIC_TRACK_IDS[0],
            'bpm': {'min': 100, 'max': 130}, 'length': {'tracks': 10}, **changes}


class PlaylistRecipeIntegrityRowTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'analysis.sqlite'

    def _store(self, name, recipe_json, format_version=2):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('INSERT INTO playlist_recipes(name, recipe_json, format_version) VALUES (?, ?, ?)',
                       (name, recipe_json, format_version))

    def _scan(self):
        result = SQLiteIntegrityScanner().scan(str(self.path))
        check = {item.check_id: item for item in result.checks}['playlist_recipes']
        findings = {item.code: item.count for item in result.findings if item.check_id == 'playlist_recipes'}
        return result, check, findings

    def test_a_valid_recipe_row_is_counted_and_clean(self):
        create_public_core_database(self.path, 11)
        self._store('Warm up', json.dumps(_recipe()))

        result, check, findings = self._scan()

        self.assertEqual(('completed', 1, 'rows', 'exact'), (check.state, check.count, check.count_unit, check.count_precision))
        self.assertEqual(({}, 'completed', True), (findings, result.stop_reason, result.implemented_scope_complete))

    def test_an_empty_recipes_table_completes_with_no_rows(self):
        create_public_core_database(self.path, 11)

        _result, check, findings = self._scan()

        self.assertEqual(('completed', 0, {}), (check.state, check.count, findings))

    def test_before_v11_the_check_is_not_applicable(self):
        create_public_core_database(self.path, 10)

        result, check, _findings = self._scan()

        self.assertEqual(('not_applicable', None, 'completed'), (check.state, check.count, result.stop_reason))

    def test_each_kind_of_bad_row_is_its_own_finding_and_names_no_recipe(self):
        create_public_core_database(self.path, 11)
        self._store('Good', json.dumps(_recipe()))
        self._store('Broken JSON', '{"format": ')
        self._store('Bytes', json.dumps(_recipe()).encode('utf-8'))
        self._store('Unknown field', json.dumps(_recipe(colour='red')))
        self._store('Inverted BPM', json.dumps(_recipe(bpm={'min': 140, 'max': 100})))
        self._store('  Padded name  ', json.dumps(_recipe()))
        self._store('Wrong version column', json.dumps(_recipe()), format_version=3)

        result, check, findings = self._scan()

        self.assertEqual(7, check.count)
        self.assertEqual({'recipe_json_invalid': 2, 'recipe_contract_invalid': 2, 'recipe_name_invalid': 1,
                          'recipe_version_invalid': 1}, findings)
        self.assertNotIn('Padded', repr(result))

    def test_the_report_counts_bad_recipe_rows_as_corruption(self):
        create_public_core_database(self.path, 11)
        self._store('Broken JSON', 'not json')

        report = CheckIntegrity(SQLiteIntegrityScanner()).execute(str(self.path))

        self.assertEqual(('corrupt', 1), (report.status, report.exit_code))
        self.assertEqual([('playlist_recipes', 'recipe_json_invalid', 'corruption', 1)],
                         [(item.check_id, item.code, item.severity, item.count) for item in report.findings])


if __name__ == '__main__':
    unittest.main()
