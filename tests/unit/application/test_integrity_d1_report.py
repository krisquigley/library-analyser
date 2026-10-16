"""Fresh application LIMITED wire gate, using only an inward fake port."""
import unittest

from music_analyzer.application.dto.integrity import IntegrityCheck, IntegrityScan
from music_analyzer.application.use_cases.check_integrity import CheckIntegrity


CHECKS = (
    ('compatibility', 'databases', 6), ('schema', 'schema_descriptors', 6),
    ('core_rows', 'rows', 6), ('metadata', 'rows', 6), ('retained_stages', 'rows', 6),
    ('current_graph', 'rows', 7), ('historical_graph', 'rows', 7),
    ('current_evidence', 'rows', 9), ('historical_evidence', 'rows', 9),
    ('sqlite_physical', 'physical_records', 6), ('sqlite_foreign_keys', 'foreign_key_records', 6),
    ('resource_access', 'databases', 6),
)


def healthy_scan(version):
    checks = []
    for name, unit, first_version in CHECKS:
        if name in ('compatibility', 'schema', 'core_rows', 'metadata', 'retained_stages', 'resource_access'):
            state, count, precision = 'completed', 1, 'exact'
        elif ((name in ('current_graph', 'historical_graph') and version >= 7)
              or (name in ('current_evidence', 'historical_evidence') and version >= 9)):
            state, count, precision = 'completed', 0, 'exact'
        else:
            state = 'not_applicable' if version < first_version else 'not_implemented'
            count, precision = None, 'unavailable'
        checks.append(IntegrityCheck(name, name, state, count, unit, precision))
    return IntegrityScan(version, tuple(checks), implemented_scope_complete=True)


def stopped_scan(stop):
    """Full frozen inventory for a stop before trustworthy version recognition."""
    from music_analyzer.application.dto.integrity import IntegrityFinding
    operational = {
        'unreadable_database': 'initial_access_failed', 'deadline': 'deadline_exceeded',
        'row_limit': 'row_limit_reached', 'utf8_limit': 'utf8_limit_reached',
        'value_limit': 'value_limit_reached', 'finding_limit': 'finding_limit_reached',
        'read_error': 'read_failed', 'cleanup_error': 'cleanup_failed', 'cancelled': 'cancelled',
    }
    checks = []
    for name, unit, first_version in CHECKS:
        state, count, precision = 'blocked', None, 'unavailable'
        if name == 'compatibility':
            if stop == 'unsupported_database':
                state, count, precision = 'completed', 1, 'exact'
            else:
                state, count, precision = 'interrupted', 0, 'lower_bound'
        elif name == 'resource_access':
            if stop == 'unsupported_database':
                state, count, precision = 'completed', 1, 'exact'
            else:
                state, count, precision = 'interrupted', 0, 'lower_bound'
        checks.append(IntegrityCheck(name, name, state, count, unit, precision))
    if stop == 'unsupported_database':
        findings = (IntegrityFinding('compatibility', 'application_id_mismatch',
                                     'compatibility', 1, count_precision='exact'),)
    else:
        findings = (IntegrityFinding('resource_access', operational[stop], 'operational', 1),)
    return IntegrityScan(checks=tuple(checks), findings=findings, supported=False,
                         stop_reason=stop, findings_truncated=stop == 'finding_limit')


class FakeScanner:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def scan(self, database, deadline_seconds=120):
        self.calls.append((database, deadline_seconds))
        return self.result


class IntegrityD1WireGate(unittest.TestCase):
    def test_every_wire_gate_field_is_independently_reached_on_healthy_versions(self):
        for version in range(6, 11):
            report = CheckIntegrity(FakeScanner(healthy_scan(version))).execute('explicit-public.sqlite')
            for field, expected in (
                    ('implemented_scope_complete', True), ('status', 'incomplete'),
                    ('complete', False), ('exit_code', 4), ('stop_reason', 'scope_not_implemented')):
                with self.subTest(version=version, field=field):
                    self.assertEqual(getattr(report, field, None), expected,
                                     'selected scope is distinct from full P7 completion')

    def test_explicit_boundary_forwards_only_requested_target_and_deadline(self):
        scanner = FakeScanner(healthy_scan(6))
        CheckIntegrity(scanner).execute('explicit-public.sqlite', 2.5)
        self.assertEqual(scanner.calls, [('explicit-public.sqlite', 2.5)],
                         'usecase must call injected scanner without constructing details')

    def test_frozen_report_revisions_and_all_twelve_checks_are_visible(self):
        report = CheckIntegrity(FakeScanner(healthy_scan(6))).execute('explicit-public.sqlite')
        for field, expected in (
                ('report_version', 1), ('coverage_revision', 'D3'),
                ('required_scope_revision', 'P7-1'), ('supported_schema_versions', (6, 7, 8, 9, 10)),
                ('schema_version', 6), ('checks', healthy_scan(6).checks)):
            with self.subTest(field=field):
                self.assertEqual(getattr(report, field, None), expected,
                                 'fixed report capability and coverage inventory must be exposed')


class IntegrityD1ReportSafety(unittest.TestCase):
    def test_corruption_keeps_finding_and_never_certifies_complete(self):
        from dataclasses import replace
        from music_analyzer.application.dto.integrity import IntegrityFinding
        corrupt = replace(healthy_scan(10), findings=(
            IntegrityFinding('core_rows', 'track_size_invalid', 'corruption', 1,
                             count_precision='exact'),))
        report = CheckIntegrity(FakeScanner(corrupt)).execute('explicit-public.sqlite')
        for field, expected in (('findings', corrupt.findings),
                                ('implemented_scope_complete', True), ('status', 'incomplete'),
                                ('complete', False), ('exit_code', 4)):
            with self.subTest(field=field):
                self.assertEqual(getattr(report, field, None), expected)

    def test_stop_reason_not_supported_flag_controls_status_and_exit(self):
        from dataclasses import replace
        for stop, status, code in (
                ('unsupported_database', 'unsupported', 3), ('unreadable_database', 'unsupported', 3),
                ('deadline', 'incomplete', 4), ('row_limit', 'incomplete', 4),
                ('utf8_limit', 'incomplete', 4), ('value_limit', 'incomplete', 4),
                ('finding_limit', 'incomplete', 4), ('read_error', 'incomplete', 4),
                ('cleanup_error', 'incomplete', 4), ('cancelled', 'incomplete', 130)):
            scan = stopped_scan(stop)
            report = CheckIntegrity(FakeScanner(scan)).execute('explicit-public.sqlite')
            for field, expected in (('stop_reason', stop), ('status', status),
                                    ('exit_code', code), ('implemented_scope_complete', False)):
                with self.subTest(stop=stop, field=field):
                    self.assertEqual(getattr(report, field, None), expected)

    def test_malformed_or_throwing_port_is_sanitized_not_echoed(self):
        from dataclasses import replace
        from music_analyzer.application.dto.integrity import IntegrityFinding

        class ThrowingScanner:
            def scan(self, database, deadline_seconds=120):
                raise RuntimeError('PRIVATE PATH SQL PAYLOAD')

        malformed = (
            IntegrityScan(stop_reason='deadline', supported=False),
            object(),
            replace(healthy_scan(6), stop_reason='PRIVATE PATH SQL PAYLOAD'),
            replace(healthy_scan(6), checks=(IntegrityCheck(
                'PRIVATE PATH SQL PAYLOAD', 'schema', 'completed', 1, 'rows', 'exact'),)),
            replace(healthy_scan(6), findings=(IntegrityFinding(
                'core_rows', 'track_size_invalid', 'corruption', True),)),
            replace(healthy_scan(6), findings=(IntegrityFinding(
                'core_rows', 'track_size_invalid', 'corruption', 2_000_001),)),
        )
        ports = [FakeScanner(scan) for scan in malformed] + [ThrowingScanner()]
        for index, port in enumerate(ports):
            report = CheckIntegrity(port).execute('PRIVATE TARGET.sqlite')
            for field, expected in (('stop_reason', 'read_error'), ('status', 'incomplete'),
                                    ('exit_code', 4), ('implemented_scope_complete', False)):
                with self.subTest(port=index, field=field):
                    self.assertEqual(getattr(report, field, None), expected)
            with self.subTest(port=index, field='safe_repr'):
                self.assertNotIn('PRIVATE', repr(report))


class IntegrityD1FakeFixtureControls(unittest.TestCase):
    def assert_strict_shape(self, scan):
        self.assertIsInstance(scan, IntegrityScan)
        self.assertEqual(type(scan.supported), bool)
        self.assertEqual(type(scan.implemented_scope_complete), bool)
        self.assertEqual(type(scan.findings_truncated), bool)
        self.assertEqual(tuple(c.check_id for c in scan.checks), tuple(c[0] for c in CHECKS))
        self.assertIsNone(scan.schema_version)
        self.assertFalse(scan.supported)
        self.assertFalse(scan.implemented_scope_complete)
        for item, (name, unit, first_version) in zip(scan.checks, CHECKS):
            self.assertEqual(item.category, name)
            self.assertEqual(item.count_unit, unit)
            if item.state in ('completed', 'interrupted'):
                self.assertEqual(type(item.count), int)
                self.assertGreaterEqual(item.count, 0)
                self.assertEqual(item.count_precision, 'exact' if item.state == 'completed' else 'lower_bound')
            else:
                self.assertEqual(item.state, 'blocked')
                self.assertIsNone(item.count)
                self.assertEqual(item.count_precision, 'unavailable')
            if name not in ('compatibility', 'resource_access'):
                self.assertEqual(item.state, 'blocked', 'unknown version cannot infer legacy N/A')
        for item in scan.findings:
            self.assertEqual(type(item.count), int)
            self.assertEqual(item.count, 1)
            self.assertEqual(item.count_unit, 'occurrences')
            if scan.stop_reason == 'unsupported_database':
                self.assertEqual((item.check_id, item.code, item.severity, item.count_precision),
                                 ('compatibility', 'application_id_mismatch', 'compatibility', 'exact'))
            else:
                expected = {
                    'unreadable_database': 'initial_access_failed', 'deadline': 'deadline_exceeded',
                    'row_limit': 'row_limit_reached', 'utf8_limit': 'utf8_limit_reached',
                    'value_limit': 'value_limit_reached', 'finding_limit': 'finding_limit_reached',
                    'read_error': 'read_failed', 'cleanup_error': 'cleanup_failed', 'cancelled': 'cancelled',
                }[scan.stop_reason]
                self.assertEqual((item.check_id, item.code, item.severity, item.count_precision),
                                 ('resource_access', expected, 'operational', 'lower_bound'))

    def test_all_stopped_fixtures_obey_frozen_input_shape(self):
        for stop in ('unsupported_database', 'unreadable_database', 'deadline', 'row_limit',
                     'utf8_limit', 'value_limit', 'finding_limit', 'read_error', 'cleanup_error', 'cancelled'):
            with self.subTest(stop=stop):
                self.assert_strict_shape(stopped_scan(stop))

    def test_empty_check_shape_is_rejected_by_fixture_oracle(self):
        with self.assertRaises(AssertionError):
            self.assert_strict_shape(IntegrityScan(stop_reason='deadline', supported=False))


class IntegrityD1RecognitionConsistency(unittest.TestCase):
    def assert_sanitized_read_error(self, scan):
        report = CheckIntegrity(FakeScanner(scan)).execute('PRIVATE TARGET.sqlite')
        self.assertEqual(report.stop_reason, 'read_error')
        self.assertEqual(report.status, 'incomplete')
        self.assertEqual(report.exit_code, 4)
        self.assertFalse(report.implemented_scope_complete)
        self.assertIsNone(report.schema_version)
        self.assertFalse(report.findings_truncated)
        self.assertEqual(tuple((f.check_id, f.code) for f in report.findings),
                         (('resource_access', 'read_failed'),))
        self.assertNotIn('PRIVATE', repr(report))

    def test_truncation_cannot_claim_completed_scope_or_another_stop(self):
        from dataclasses import replace
        self.assert_sanitized_read_error(replace(healthy_scan(6), findings_truncated=True))
        self.assert_sanitized_read_error(replace(stopped_scan('deadline'), findings_truncated=True))
        report = CheckIntegrity(FakeScanner(stopped_scan('finding_limit'))).execute('explicit-public.sqlite')
        self.assertEqual(report.stop_reason, 'finding_limit')
        self.assertTrue(report.findings_truncated)
        self.assertFalse(report.implemented_scope_complete)
        self.assertEqual(report.exit_code, 4)

    def test_unsupported_database_requires_completed_compatibility_rejection(self):
        from dataclasses import replace
        self.assert_sanitized_read_error(replace(stopped_scan('deadline'), stop_reason='unsupported_database'))
        self.assert_sanitized_read_error(replace(stopped_scan('unsupported_database'), findings=()))
        report = CheckIntegrity(FakeScanner(stopped_scan('unsupported_database'))).execute('explicit-public.sqlite')
        self.assertEqual(report.stop_reason, 'unsupported_database')
        self.assertEqual(report.status, 'unsupported')
        self.assertEqual(report.exit_code, 3)
        self.assertFalse(report.implemented_scope_complete)

    def test_contradictory_recognition_dependency_and_database_counts_use_safe_fallback(self):
        from dataclasses import replace
        from music_analyzer.application.dto.integrity import IntegrityFinding
        healthy = healthy_scan(6)
        blocked_schema = tuple(replace(c, state='blocked', count=None, count_precision='unavailable')
                               if c.check_id == 'schema' else c for c in healthy.checks)
        bad_count = lambda name: tuple(replace(c, count=999) if c.check_id == name else c
                                       for c in healthy.checks)
        cases = (
            replace(healthy, stop_reason='unsupported_database', implemented_scope_complete=False),
            replace(healthy, findings=(IntegrityFinding('compatibility', 'application_id_mismatch',
                                                       'compatibility', 1, count_precision='exact'),)),
            replace(healthy, checks=blocked_schema, stop_reason='schema_blocked', implemented_scope_complete=False),
            replace(healthy, findings=(IntegrityFinding('schema', 'schema_checks_mismatch',
                                                       'corruption', 1, count_precision='exact'),),
                    stop_reason='schema_blocked', implemented_scope_complete=False),
            replace(healthy, checks=bad_count('compatibility')),
            replace(healthy, checks=bad_count('resource_access')),
            replace(stopped_scan('deadline'), stop_reason='scope_not_implemented'),
        )
        for index, scan in enumerate(cases):
            report = CheckIntegrity(FakeScanner(scan)).execute('explicit-public.sqlite')
            for field, expected in (('stop_reason', 'read_error'), ('schema_version', None),
                                    ('implemented_scope_complete', False)):
                with self.subTest(case=index, field=field):
                    self.assertEqual(getattr(report, field, None), expected,
                                     'contradictory port result is malformed, not recognized coverage')


class IntegrityD1InterruptedDependency(unittest.TestCase):
    def test_interrupted_schema_cannot_authorize_started_core(self):
        from dataclasses import replace
        healthy = healthy_scan(6)
        for core_state in ('completed', 'interrupted'):
            checks = tuple(replace(c, state='interrupted', count=1, count_precision='lower_bound')
                           if c.check_id == 'schema' else (
                               replace(c, state=core_state, count=1,
                                       count_precision='exact' if core_state == 'completed' else 'lower_bound')
                               if c.check_id == 'core_rows' else c) for c in healthy.checks)
            malformed = replace(healthy, checks=checks, stop_reason='read_error', implemented_scope_complete=False)
            report = CheckIntegrity(FakeScanner(malformed)).execute('explicit-public.sqlite')
            with self.subTest(core_state=core_state, field='fallback_recognition'):
                self.assertIsNone(report.schema_version, 'malformed dependency state needs sanitized fallback')
            with self.subTest(core_state=core_state, field='fallback_core'):
                self.assertEqual(next(c for c in report.checks if c.check_id == 'core_rows').state, 'blocked')
