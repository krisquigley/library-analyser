"""Issue #139: the integrity report accepts the playlist recipe row check only where it applies."""
from dataclasses import replace
import unittest

from music_analyzer.application.dto.integrity import IntegrityFinding
from music_analyzer.application.use_cases.check_integrity import CHECKS, CheckIntegrity
from tests.unit.application.test_integrity_d3b_completion import FakeScanner, changed, completed_scan


def _recipe_finding(code='recipe_contract_invalid', count=1, precision='exact'):
    return IntegrityFinding('playlist_recipes', code, 'corruption', count, count_precision=precision)


def _report(scan):
    return CheckIntegrity(FakeScanner(scan)).execute('synthetic.sqlite')


class PlaylistRecipeCheckReportTests(unittest.TestCase):
    def test_the_recipe_check_counts_rows_and_starts_at_schema_v11(self):
        self.assertIn(('playlist_recipes', 'rows', 11), CHECKS)

    def test_each_recipe_code_on_a_v11_scan_is_reported_as_corruption(self):
        for code in ('recipe_json_invalid', 'recipe_contract_invalid', 'recipe_name_invalid', 'recipe_version_invalid'):
            with self.subTest(code=code):
                scan = replace(changed(completed_scan(11), 'playlist_recipes', count=3), findings=(_recipe_finding(code),))

                report = _report(scan)

                self.assertEqual(('corrupt', 1, (_recipe_finding(code),)), (report.status, report.exit_code, report.findings))

    def test_before_v11_the_recipe_check_must_be_not_applicable(self):
        for version in range(6, 11):
            with self.subTest(version=version):
                scan = changed(completed_scan(version), 'playlist_recipes', state='completed', count=0,
                               count_precision='exact')

                self.assertEqual('read_error', _report(scan).stop_reason)

    def test_a_recipe_finding_before_v11_is_refused(self):
        scan = replace(completed_scan(10), findings=(_recipe_finding(),))

        self.assertEqual('read_error', _report(scan).stop_reason)

    def test_a_recipe_finding_cannot_count_more_rows_than_were_read(self):
        scan = replace(changed(completed_scan(11), 'playlist_recipes', count=1), findings=(_recipe_finding(count=2),))

        self.assertEqual('read_error', _report(scan).stop_reason)

    def test_an_unknown_recipe_code_is_refused(self):
        scan = replace(changed(completed_scan(11), 'playlist_recipes', count=1),
                       findings=(_recipe_finding('recipe_mood_invalid'),))

        self.assertEqual('read_error', _report(scan).stop_reason)


if __name__ == '__main__':
    unittest.main()
