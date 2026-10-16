"""Fresh real-parser CLI packet; fake inward scanner avoids SQLite overlap."""
from contextlib import redirect_stdout, redirect_stderr
import io
import json
import unittest
from unittest.mock import patch

from music_analyzer.frameworks.cli import main as cli
from tests.unit.application.test_integrity_d1_report import FakeScanner, healthy_scan, stopped_scan


def invoke(argv, scan=None):
    stdout, stderr = io.StringIO(), io.StringIO()
    scanner = FakeScanner(healthy_scan(6) if scan is None else scan)
    with patch.object(cli, 'SQLiteIntegrityScanner', return_value=scanner), \
            patch.object(cli, 'load_settings', side_effect=AssertionError('forbidden Settings')), \
            patch.object(cli, 'build_models', side_effect=AssertionError('forbidden models')), \
            patch.object(cli, 'SQLiteAnalysisRepository', side_effect=AssertionError('forbidden writer')), \
            redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            code = cli.main(argv)
        except SystemExit as error:
            code = error.code
    return code, stdout.getvalue(), stderr.getvalue(), scanner.calls


class IntegrityD1RealCLI(unittest.TestCase):
    def test_real_syntax_reports_limited_and_last_explicit_database_wins(self):
        variants = (
            ['integrity', '--database', 'selected.sqlite', '--json'],
            ['--database', 'selected.sqlite', 'integrity', '--json'],
            ['--database=PRIVATE-earlier.sqlite', 'integrity', '--database=selected.sqlite', '--json'],
            ['integrity', '--database', 'PRIVATE-earlier.sqlite', '--database', 'selected.sqlite', '--json'],
        )
        for argv in variants:
            code, stdout, stderr, calls = invoke(argv)
            # Empty scaffold stdout is treated as absent wire data, never a parse-error RED.
            payload = json.loads(stdout) if stdout else {}
            for field, expected in (('status', 'incomplete'), ('complete', False),
                                    ('exit_code', 4), ('stop_reason', 'scope_not_implemented')):
                with self.subTest(argv=argv, field=field):
                    self.assertEqual(payload.get(field), expected)
            with self.subTest(argv=argv, field='port_call'):
                self.assertEqual(calls, [('selected.sqlite', 120)])
            self.assertEqual(code, 4)
            self.assertNotIn('PRIVATE', stdout + stderr)

    def test_unsupported_and_prerecognition_deadline_use_distinct_exits(self):
        for stop, expected in (('unsupported_database', 3), ('unreadable_database', 3),
                               ('deadline', 4), ('cleanup_error', 4), ('cancelled', 130)):
            code, stdout, stderr, calls = invoke(['integrity', '--database', 'selected.sqlite', '--json'], stopped_scan(stop))
            payload = json.loads(stdout) if stdout else {}
            with self.subTest(stop=stop, field='exit'):
                self.assertEqual(code, expected)
            with self.subTest(stop=stop, field='reason'):
                self.assertEqual(payload.get('stop_reason'), stop)

    def test_usage_rejects_nonexplicit_irrelevant_and_invalid_options_before_access(self):
        variants = (
            ['integrity'],
            ['--config', 'PRIVATE-config.toml', 'integrity', '--database', 'selected.sqlite'],
            ['--model-directory', 'PRIVATE-models', 'integrity', '--database', 'selected.sqlite'],
            ['integrity', '--database', 'selected.sqlite', '--PRIVATE-irrelevant'],
            ['integrity', '--database', 'selected.sqlite', '--audit-deadline-seconds', 'nan'],
            ['integrity', '--database', 'selected.sqlite', '--audit-deadline-seconds', '121'],
            ['integrity', '--database', 'selected.sqlite', '--audit-deadline-seconds', 'PRIVATE-invalid'],
            ['integrity', '--database'],
        )
        for argv in variants:
            code, stdout, stderr, calls = invoke(argv)
            with self.subTest(argv=argv, field='usage'):
                self.assertEqual(code, 2)
            with self.subTest(argv=argv, field='privacy'):
                self.assertNotIn('PRIVATE', stderr)
            self.assertEqual(stdout, '')
            self.assertEqual(calls, [])

    def test_short_deadline_and_text_output_forward_without_unrelated_startup(self):
        code, stdout, stderr, calls = invoke(['integrity', '--database', 'selected.sqlite', '--audit-deadline-seconds', '2.5'])
        with self.subTest(field='port_call'):
            self.assertEqual(calls, [('selected.sqlite', 2.5)])
        with self.subTest(field='text'):
            self.assertIn('D3 offline integrity diagnostic', stdout)
        self.assertEqual(code, 4)
        self.assertEqual(stderr, '')


class IntegrityD1AbbreviationPrivacy(unittest.TestCase):
    def test_root_option_abbreviation_values_cannot_disable_integrity_privacy(self):
        for option in ('--data', '--con', '--model-d'):
            argv = [option, 'doctor', 'integrity', '--database', 'selected.sqlite', '--secret', 'PRIVATE-value']
            code, stdout, stderr, calls = invoke(argv)
            with self.subTest(option=option, field='privacy'):
                self.assertNotIn('PRIVATE', stderr, 'root option operand is not another command')
            self.assertEqual(code, 2)
            self.assertEqual(stdout, '')
            self.assertEqual(calls, [])

    def test_nonintegrity_abbreviations_and_integrity_named_operand_are_unchanged(self):
        class Doctor:
            def execute(self):
                class Report:
                    foundation_ready = True
                return Report()
        stdout = io.StringIO()
        with patch.object(cli, 'build_doctor', return_value=Doctor()) as doctor, \
                patch.object(cli, 'present_doctor', return_value='doctor-control'), redirect_stdout(stdout):
            code = cli.main(['--data', 'integrity', 'doctor'])
        self.assertEqual(code, 0)
        doctor.assert_called_once_with(database='integrity')
        self.assertEqual(stdout.getvalue(), 'doctor-control\n')
