"""Real CLI dispatch, public healthy SQLite and inward completion/privacy controls."""
from contextlib import closing, redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import sqlite3
import unittest
from unittest.mock import patch

from music_analyzer.frameworks.cli import main as cli
from tests.integration.infrastructure.integrity_d1_public_fixture import create_public_core_database
from tests.integration.test_integrity_d1_cli import invoke
from tests.unit.application.test_integrity_d3b_completion import CountedAssertions, completed_scan, corruption, changed
from dataclasses import replace


def real_invoke(argv):
    stdout, stderr = io.StringIO(), io.StringIO()
    with patch.object(cli, 'load_settings', side_effect=AssertionError('forbidden Settings')), \
            patch.object(cli, 'build_models', side_effect=AssertionError('forbidden models')), \
            patch.object(cli, 'SQLiteAnalysisRepository', side_effect=AssertionError('forbidden writer')), \
            redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            code = cli.main(argv)
        except SystemExit as error:
            code = error.code
    return code, stdout.getvalue(), stderr.getvalue()


class D3bCLITests(CountedAssertions):
    def test_real_public_genuine_six_through_ten_are_clean_complete_zero(self):
        with tempfile.TemporaryDirectory() as root:
            for version in range(6, 11):
                path = Path(root) / ('PRIVATE-public-v%d.sqlite' % version)
                create_public_core_database(path, version)
                for suffix in ([], ['--json']):
                    code, stdout, stderr = real_invoke(['integrity', '--database', str(path)] + suffix)
                    with self.subTest(version=version, json=bool(suffix)):
                        self.assertEqual(code, 0)
                        self.assertNotIn('PRIVATE', stdout + stderr)
                        self.assertEqual(stderr, '')
                        if suffix:
                            wire = json.loads(stdout)
                            self.assertEqual((wire['exit_code'], wire['status'], wire['complete']),
                                             (0, 'clean', True))
                            self.assertEqual((wire['coverage_revision'], wire['stop_reason']), ('D3', 'completed'))
                            self.assertEqual(wire['schema_version'], version)
                        else:
                            self.assertIn(' complete=true ', stdout)
                            self.assertIn('status=clean', stdout)
                            self.assertIn('exit=0', stdout)

    def test_real_public_orphan_is_complete_corrupt_one_with_private_fk_ownership(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'PRIVATE-orphan.sqlite'
            create_public_core_database(path, 10)
            with closing(sqlite3.connect(path)) as db:
                db.execute('PRAGMA foreign_keys=OFF')
                db.execute('INSERT INTO track_audio VALUES(?,?,?,?,?)',
                           ('sha256:' + '9' * 64, 1.0, 'mutagen', 'eligible', ''))
                db.commit()
            for suffix in ([], ['--json']):
                code, stdout, stderr = real_invoke(['integrity', '--database', str(path)] + suffix)
                with self.subTest(json=bool(suffix)):
                    self.assertEqual(code, 1)
                    self.assertEqual(stderr, '')
                    for forbidden in ('PRIVATE', 'sha256:', 'rowid', 'SELECT ', 'Traceback'):
                        self.assertNotIn(forbidden, stdout + stderr)
                    if suffix:
                        wire = json.loads(stdout)
                        self.assertEqual((wire['status'], wire['complete'], wire['stop_reason']),
                                         ('corrupt', True, 'completed'))
                        findings = [f for f in wire['findings'] if f['check_id'] == 'sqlite_foreign_keys']
                        self.assertEqual(findings, [{'check_id': 'sqlite_foreign_keys',
                            'code': 'sqlite_foreign_key_invalid', 'severity': 'corruption', 'count': 1,
                            'count_unit': 'occurrences', 'count_precision': 'exact'}])
                    else:
                        self.assertIn(' complete=true ', stdout)
                        self.assertIn('status=corrupt', stdout)
                        self.assertIn('exit=1', stdout)

    def test_real_parser_fake_completion_clean_and_corrupt_text_json_exit_agree(self):
        for corrupt in (False, True):
            with self.subTest(corrupt=corrupt):
                scan = completed_scan()
                if corrupt: scan = replace(scan, findings=(corruption(),))
                outputs = []
                for suffix in ([], ['--json']):
                    code, stdout, stderr, calls = invoke(
                        ['--database', 'PRIVATE-earlier.sqlite', 'integrity',
                         '--database', 'PRIVATE-selected.sqlite'] + suffix, scan)
                    outputs.append(stdout)
                    with self.subTest(corrupt=corrupt, json=bool(suffix)):
                        self.assertEqual(code, 1 if corrupt else 0)
                        self.assertEqual(calls, [('PRIVATE-selected.sqlite', 120)])
                        self.assertEqual(stderr, '')
                        self.assertNotIn('PRIVATE', stdout + stderr)
                wire = json.loads(outputs[1])
                self.assertTrue(wire['complete'])
                self.assertIn(' complete=true ', outputs[0])
                self.assertIn('status=' + wire['status'], outputs[0])

    def test_late_failure_corruption_and_cancellation_have_private_text_json_exit_agreement(self):
        from music_analyzer.application.dto.integrity import IntegrityFinding
        for reason, codes, expected in (
                ('read_error', ('read_failed',), 4),
                ('deadline', ('deadline_exceeded',), 4),
                ('cleanup_error', ('cleanup_failed',), 4),
                ('cancelled', ('cleanup_failed', 'cancelled'), 130)):
            scan = changed(completed_scan(), 'resource_access', state='interrupted', count=0,
                           count_precision='lower_bound')
            scan = replace(scan, implemented_scope_complete=False, stop_reason=reason,
                           findings=(corruption(),) + tuple(IntegrityFinding(
                               'resource_access', code, 'operational', 1) for code in codes))
            for suffix in ([], ['--json']):
                code, stdout, stderr, calls = invoke(
                    ['integrity', '--database', 'PRIVATE-selected.sqlite'] + suffix, scan)
                with self.subTest(reason=reason, json=bool(suffix)):
                    self.assertEqual(code, expected)
                    self.assertEqual(calls, [('PRIVATE-selected.sqlite', 120)])
                    self.assertEqual(stderr, '')
                    self.assertNotIn('PRIVATE', stdout)
                    if suffix:
                        wire = json.loads(stdout)
                        self.assertEqual((wire['stop_reason'], wire['exit_code'], wire['complete']),
                                         (reason, expected, False))
                        self.assertEqual(wire['findings'][0]['code'], 'sqlite_integrity_invalid')
                    else:
                        self.assertIn(' complete=false ', stdout)
                        self.assertIn('exit=' + str(expected), stdout)

    def test_explicit_database_and_invalid_options_fail_before_access_privately_controls(self):
        for argv in (['integrity'], ['integrity', '--database'],
                     ['--config', 'PRIVATE-config', 'integrity', '--database', 'selected.sqlite'],
                     ['integrity', '--database', 'selected.sqlite', '--secret', 'PRIVATE-value'],
                     ['integrity', '--database', 'selected.sqlite', '--audit-deadline-seconds', 'nan']):
            code, stdout, stderr, calls = invoke(argv, completed_scan())
            with self.subTest(argv=argv):
                self.assertEqual((code, stdout, calls), (2, '', []))
                self.assertNotIn('PRIVATE', stderr)

    def test_raw_scanner_exception_never_reaches_real_cli_controls(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        class RaisingScanner:
            def scan(self, database, deadline_seconds):
                raise ValueError('PRIVATE SQL rowid=42')
        with patch.object(cli, 'SQLiteIntegrityScanner', return_value=RaisingScanner()), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            code = cli.main(['integrity', '--database', 'PRIVATE-target.sqlite', '--json'])
        wire = json.loads(stdout.getvalue())
        self.assertEqual((code, wire['stop_reason'], wire['complete']), (4, 'read_error', False))
        self.assertNotIn('PRIVATE', stdout.getvalue() + stderr.getvalue())
        self.assertNotIn('rowid', stdout.getvalue() + stderr.getvalue())
