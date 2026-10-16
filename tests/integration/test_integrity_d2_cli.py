"""Full-D2 delivery through the real CLI; supplementary to retained policy RED."""
from contextlib import redirect_stderr, redirect_stdout, closing
from dataclasses import replace
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from music_analyzer.application.dto.integrity import IntegrityFinding
from music_analyzer.frameworks.cli import main as cli
from tests.integration.infrastructure.integrity_d2_evidence_public_fixture import (
    create_public_evidence_database, OLD_RUNS,
)
from tests.integration.test_integrity_d1_cli import invoke
from tests.unit.application.test_integrity_d2_evidence_report import evidence_scan


class IntegrityD2CLI(unittest.TestCase):
    def test_real_old_corruption_json_and_text_are_sanitized_noncertificates(self):
        for version in (9, 10):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'PRIVATE-library.sqlite'
                create_public_evidence_database(path, version)
                with closing(sqlite3.connect(path)) as db:
                    db.execute('UPDATE graph_feature_evidence SET evidence_json=? WHERE run_id=?',
                               ('PRIVATE broken JSON', OLD_RUNS[0]))
                    db.commit()
                before = path.read_bytes()
                for json_output in (False, True):
                    out, err = io.StringIO(), io.StringIO()
                    argv = ['integrity', '--database', str(path)] + (['--json'] if json_output else [])
                    with patch.object(cli, 'load_settings', side_effect=AssertionError('forbidden settings')), \
                            patch.object(cli, 'SQLiteAnalysisRepository', side_effect=AssertionError('forbidden writer')), \
                            redirect_stdout(out), redirect_stderr(err):
                        code = cli.main(argv)
                    self.assertEqual(code, 4)
                    self.assertEqual(err.getvalue(), '')
                    self.assertNotIn('PRIVATE', out.getvalue())
                    self.assertNotIn(OLD_RUNS[0], out.getvalue())
                    self.assertEqual(path.read_bytes(), before)
                    if json_output:
                        report = json.loads(out.getvalue())
                        self.assertEqual((report['coverage_revision'], report['report_version'],
                                          report['required_scope_revision']), ('D3a', 1, 'P7-1'))
                        self.assertFalse(report['complete'])
                        self.assertTrue(report['implemented_scope_complete'])
                        checks = {c['check_id']: c for c in report['checks']}
                        for owner in ('current_evidence', 'historical_evidence'):
                            self.assertEqual((checks[owner]['state'], checks[owner]['count'],
                                              checks[owner]['count_precision']), ('completed', 2, 'exact'))
                        self.assertEqual([(f['check_id'], f['code'], f['count'], f['count_precision'])
                                          for f in report['findings']],
                                         [('historical_evidence', 'evidence_json_invalid', 1, 'exact')])
                    else:
                        self.assertIn('coverage_revision=D3a', out.getvalue())
                        self.assertIn('historical_evidence/evidence_json_invalid', out.getvalue())
                        self.assertIn('complete=false', out.getvalue())

    def test_interrupted_evidence_prefix_is_presented_without_certification(self):
        scan = evidence_scan()
        checks = tuple(replace(c, state='interrupted', count=1, count_precision='lower_bound')
                       if c.check_id == 'historical_evidence' else
                       replace(c, state='interrupted', count=0, count_precision='lower_bound')
                       if c.check_id == 'resource_access' else c for c in scan.checks)
        findings = (IntegrityFinding('historical_evidence', 'evidence_json_invalid', 'corruption', 1),
                    IntegrityFinding('resource_access', 'read_failed', 'operational', 1))
        scan = replace(scan, checks=checks, findings=findings, stop_reason='read_error',
                       implemented_scope_complete=False)
        for json_output in (False, True):
            code, out, err, calls = invoke(['integrity', '--database', 'PRIVATE-target'] +
                                         (['--json'] if json_output else []), scan)
            self.assertEqual(code, 4)
            self.assertEqual(err, '')
            self.assertNotIn('PRIVATE', out)
            self.assertEqual(calls, [('PRIVATE-target', 120)])
            if json_output:
                report = json.loads(out)
                self.assertEqual(report['stop_reason'], 'read_error')
                self.assertFalse(report['implemented_scope_complete'])
                self.assertFalse(report['complete'])
                self.assertEqual(report['schema_version'], 10)
                self.assertEqual(report['findings'][0]['count_precision'], 'lower_bound')
            else:
                self.assertIn('precision=lower_bound', out)
                self.assertIn('implemented_scope_complete=false', out)
