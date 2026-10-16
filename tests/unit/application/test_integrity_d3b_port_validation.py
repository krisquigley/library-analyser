"""Regression policy for untrusted diagnostic ports; no persistence or SQLite."""
from dataclasses import replace
import unittest

from music_analyzer.application.dto.integrity import IntegrityCheck, IntegrityFinding, IntegrityScan
from music_analyzer.application.use_cases.check_integrity import CheckIntegrity


CHECKS = (
    ('compatibility', 'databases'), ('schema', 'schema_descriptors'),
    ('core_rows', 'rows'), ('metadata', 'rows'), ('retained_stages', 'rows'),
    ('current_graph', 'rows'), ('historical_graph', 'rows'),
    ('current_evidence', 'rows'), ('historical_evidence', 'rows'),
    ('sqlite_physical', 'physical_records'), ('sqlite_foreign_keys', 'foreign_key_records'),
    ('resource_access', 'databases'),
)
ROW_CODES = {
    'core_rows': ('track_identity_invalid', 'track_digest_invalid', 'track_size_invalid',
                  'track_audio_missing', 'track_audio_orphan', 'track_audio_duration_invalid',
                  'track_audio_policy_invalid'),
    'metadata': ('metadata_json_invalid', 'metadata_contract_invalid', 'metadata_delivery_invalid'),
    'retained_stages': ('stage_json_invalid', 'stage_contract_invalid', 'stage_identity_invalid',
                        'stage_payload_oversized', 'stage_delivery_invalid'),
    'current_graph': ('graph_lifecycle_invalid', 'graph_edge_invalid'),
    'historical_graph': ('graph_lifecycle_invalid', 'graph_edge_invalid'),
    'current_evidence': ('evidence_envelope_invalid', 'evidence_link_invalid', 'evidence_json_invalid',
                         'evidence_contract_invalid', 'evidence_feature_invalid', 'evidence_summary_invalid',
                         'evidence_fingerprint_invalid', 'evidence_delivery_invalid', 'evidence_payload_oversized'),
    'historical_evidence': ('evidence_envelope_invalid', 'evidence_link_invalid', 'evidence_json_invalid',
                            'evidence_contract_invalid', 'evidence_feature_invalid', 'evidence_summary_invalid',
                            'evidence_fingerprint_invalid', 'evidence_delivery_invalid', 'evidence_payload_oversized'),
}


def completed_scan():
    return IntegrityScan(10, tuple(
        IntegrityCheck(name, name, 'completed',
                       1 if name in ('compatibility', 'sqlite_physical', 'resource_access') else 0,
                       unit, 'exact') for name, unit in CHECKS),
        implemented_scope_complete=True, stop_reason='completed')


def failed_schema_scan(version, schema_state):
    scan = replace(completed_scan(), schema_version=version)
    for owner in ('core_rows', 'metadata', 'retained_stages', 'current_graph',
                  'historical_graph', 'current_evidence', 'historical_evidence',
                  'sqlite_physical', 'sqlite_foreign_keys'):
        state = ('not_applicable' if version == 6 and owner in (
            'current_graph', 'historical_graph', 'current_evidence', 'historical_evidence')
                 else 'blocked')
        scan = changed(scan, owner, state=state, count=None, count_precision='unavailable')
    if schema_state == 'blocked':
        scan = changed(scan, 'schema', state='blocked', count=None, count_precision='unavailable')
        return interrupted(scan)
    return replace(scan, implemented_scope_complete=False, stop_reason='schema_blocked',
                   findings=(corruption('schema', 'schema_checks_mismatch'),))


def changed(scan, owner, **fields):
    return replace(scan, checks=tuple(replace(item, **fields) if item.check_id == owner else item
                                      for item in scan.checks))


def corruption(owner, code, count=1, precision='exact'):
    return IntegrityFinding(owner, code, 'corruption', count, count_precision=precision)


def interrupted(scan, reason='read_error', codes=('read_failed',)):
    scan = changed(scan, 'resource_access', state='interrupted', count=0,
                   count_precision='lower_bound')
    return replace(scan, implemented_scope_complete=False, stop_reason=reason,
                   findings=scan.findings + tuple(IntegrityFinding('resource_access', code, 'operational', 1)
                                                  for code in codes))


class FakeScanner:
    def __init__(self, result):
        self.result = result

    def scan(self, database, deadline_seconds):
        return self.result


def execute(scan):
    return CheckIntegrity(FakeScanner(scan)).execute('PRIVATE-target.sqlite')


class CompletedOwnerPortValidationTests(unittest.TestCase):
    def assert_sanitized(self, scan):
        report = execute(scan)
        self.assertEqual((report.schema_version, report.status, report.stop_reason, report.exit_code,
                          report.complete, report.implemented_scope_complete),
                         (None, 'incomplete', 'read_error', 4, False, False))
        self.assertEqual(report.findings,
                         (IntegrityFinding('resource_access', 'read_failed', 'operational', 1),))
        self.assertEqual(tuple((item.check_id, item.state, item.count, item.count_precision)
                               for item in report.checks),
                         tuple((name, 'interrupted' if name == 'resource_access' else 'blocked',
                                0 if name == 'resource_access' else None,
                                'lower_bound' if name == 'resource_access' else 'unavailable')
                               for name, unit in CHECKS))
        self.assertNotIn('PRIVATE', repr(report))

    def test_failed_schema_preserves_blocked_physical_and_foreign_key_controls(self):
        for version in (6, 10):
            for schema_state in ('completed', 'blocked'):
                with self.subTest(version=version, schema_state=schema_state):
                    scan = failed_schema_scan(version, schema_state)
                    report = execute(scan)
                    self.assertEqual((report.schema_version, report.stop_reason, report.exit_code,
                                      report.complete, report.implemented_scope_complete),
                                     (version, scan.stop_reason, 4, False, False))
                    self.assertEqual(report.checks, scan.checks)
                    self.assertEqual(report.findings, scan.findings)

    def test_failed_schema_rejects_each_finding_free_physical_and_foreign_key_owner(self):
        for version in (6, 10):
            for schema_state in ('completed', 'blocked'):
                control = failed_schema_scan(version, schema_state)
                for owner in ('sqlite_physical', 'sqlite_foreign_keys'):
                    for state in ('completed', 'interrupted'):
                        with self.subTest(version=version, schema_state=schema_state,
                                          owner=owner, state=state):
                            # Change just one owner from its valid blocked control.
                            count = 1 if owner == 'sqlite_physical' and state == 'completed' else 0
                            scan = changed(control, owner, state=state, count=count,
                                           count_precision='exact' if state == 'completed' else 'lower_bound')
                            self.assert_sanitized(scan)

    def test_completed_physical_and_foreign_key_findings_survive_later_failures(self):
        for owner, code in (('sqlite_physical', 'sqlite_integrity_invalid'),
                            ('sqlite_foreign_keys', 'sqlite_foreign_key_invalid')):
            for reason, codes, exit_code in (
                    ('read_error', ('read_failed',), 4),
                    ('cleanup_error', ('read_failed', 'cleanup_failed'), 4),
                    ('cancelled', ('read_failed', 'cleanup_failed', 'cancelled'), 130)):
                with self.subTest(owner=owner, reason=reason):
                    scan = changed(completed_scan(), owner, count=1)
                    scan = interrupted(replace(scan, findings=(corruption(owner, code),)), reason, codes)
                    report = execute(scan)
                    self.assertEqual((report.schema_version, report.stop_reason, report.exit_code,
                                      report.complete, report.implemented_scope_complete),
                                     (10, reason, exit_code, False, False))
                    self.assertEqual(report.checks, scan.checks)
                    self.assertEqual(set(report.findings), set(scan.findings))

    def test_schema_blocked_preserves_legacy_lower_bound_schema_mismatch(self):
        # Schema descriptor findings are not row-owned semantic predicates;
        # preserve this existing port contract independently of row validation.
        scan = completed_scan()
        for owner in ('core_rows', 'metadata', 'retained_stages', 'current_graph',
                      'historical_graph', 'current_evidence', 'historical_evidence',
                      'sqlite_physical', 'sqlite_foreign_keys'):
            scan = changed(scan, owner, state='blocked', count=None, count_precision='unavailable')
        scan = replace(scan, implemented_scope_complete=False, stop_reason='schema_blocked',
                       findings=(corruption('schema', 'schema_checks_mismatch',
                                            precision='lower_bound'),))
        report = execute(scan)
        self.assertEqual((report.schema_version, report.stop_reason, report.exit_code, report.complete),
                         (10, 'schema_blocked', 4, False))
        self.assertEqual(report.checks, scan.checks)
        self.assertEqual(report.findings, scan.findings)

    def test_schema_blocked_core_cannot_claim_exact_corruption(self):
        scan = completed_scan()
        for owner in ('core_rows', 'metadata', 'retained_stages', 'current_graph',
                      'historical_graph', 'current_evidence', 'historical_evidence',
                      'sqlite_physical', 'sqlite_foreign_keys'):
            scan = changed(scan, owner, state='blocked', count=None, count_precision='unavailable')
        scan = replace(scan, implemented_scope_complete=False, stop_reason='schema_blocked',
                       findings=(corruption('schema', 'schema_checks_mismatch',
                                            precision='lower_bound'),))
        for owner, code in (('core_rows', 'track_size_invalid'),
                            ('metadata', 'metadata_json_invalid'),
                            ('current_graph', 'graph_edge_invalid')):
            with self.subTest(owner=owner):
                self.assert_sanitized(replace(scan, findings=scan.findings + (corruption(owner, code),)))

    def test_interrupted_core_and_graph_codes_require_lower_bound_precision(self):
        for owner in ('core_rows', 'current_graph', 'historical_graph'):
            codes = (ROW_CODES[owner] if owner == 'core_rows' else
                     ('graph_lifecycle_invalid', 'graph_counts_invalid', 'graph_pointer_invalid',
                      'graph_mirror_invalid', 'graph_edge_invalid'))
            for code in codes:
                for precision in ('exact', 'lower_bound'):
                    with self.subTest(owner=owner, code=code, precision=precision):
                        scan = changed(completed_scan(), owner, state='interrupted', count=1,
                                       count_precision='lower_bound')
                        scan = interrupted(replace(scan, findings=(corruption(
                            owner, code, precision=precision),)))
                        if precision == 'exact':
                            self.assert_sanitized(scan)
                        else:
                            report = execute(scan)
                            self.assertEqual((report.schema_version, report.stop_reason, report.exit_code,
                                              report.complete, report.implemented_scope_complete),
                                             (10, 'read_error', 4, False, False))
                            self.assertEqual(report.checks, scan.checks)
                            self.assertEqual(set(report.findings), set(scan.findings))

    def test_zero_completed_owner_cannot_claim_one_lower_bound_corruption(self):
        for owner in ('core_rows', 'current_graph', 'current_evidence'):
            with self.subTest(owner=owner):
                self.assert_sanitized(replace(completed_scan(), findings=(
                    corruption(owner, ROW_CODES[owner][0], precision='lower_bound'),)))

    def test_completed_row_owners_require_exact_findings_even_with_available_rows(self):
        for owner, codes in ROW_CODES.items():
            with self.subTest(owner=owner):
                scan = changed(completed_scan(), owner, count=1)
                self.assert_sanitized(replace(scan, findings=(
                    corruption(owner, codes[0], precision='lower_bound'),)))

    def test_each_row_bounded_code_cannot_exceed_its_completed_owner(self):
        for owner, codes in ROW_CODES.items():
            for code in codes:
                for owner_count in (0, 1):
                    with self.subTest(owner=owner, code=code, owner_count=owner_count):
                        scan = changed(completed_scan(), owner, count=owner_count)
                        self.assert_sanitized(replace(scan, findings=(
                            corruption(owner, code, owner_count + 1),)))

    def test_each_row_bounded_code_cannot_exceed_its_interrupted_owner(self):
        for owner, codes in ROW_CODES.items():
            for code in codes:
                if owner == 'core_rows' and code == 'track_audio_orphan':
                    continue  # Orphan markers precede audio semantic-row delivery.
                with self.subTest(owner=owner, code=code):
                    scan = changed(completed_scan(), owner, state='interrupted', count=1,
                                   count_precision='lower_bound')
                    scan = replace(scan, findings=(corruption(owner, code, 2, 'lower_bound'),))
                    self.assert_sanitized(interrupted(scan))

    def test_interrupted_orphan_prefix_retains_lower_bound_and_stop_precedence(self):
        # Relation markers can be observed before the audio value rows that
        # contribute semantic core work; no phantom row may be charged.
        for owner_count, orphan_count in ((0, 1), (0, 2), (1, 2)):
            for reason, codes, exit_code in (
                    ('read_error', ('read_failed',), 4),
                    ('cleanup_error', ('read_failed', 'cleanup_failed'), 4),
                    ('cancelled', ('read_failed', 'cleanup_failed', 'cancelled'), 130)):
                with self.subTest(owner_count=owner_count, orphan_count=orphan_count,
                                  reason=reason):
                    scan = changed(completed_scan(), 'core_rows', state='interrupted',
                                   count=owner_count, count_precision='lower_bound')
                    scan = replace(scan, findings=(corruption(
                        'core_rows', 'track_audio_orphan', orphan_count, 'lower_bound'),))
                    scan = interrupted(scan, reason, codes)
                    report = execute(scan)
                    self.assertEqual((report.schema_version, report.stop_reason, report.exit_code,
                                      report.complete, report.implemented_scope_complete),
                                     (10, reason, exit_code, False, False))
                    self.assertEqual(report.checks, scan.checks)
                    self.assertEqual(set(report.findings), set(scan.findings))

    def test_interrupted_orphan_overcount_requires_lower_bound_precision(self):
        for owner_count in (0, 1):
            with self.subTest(owner_count=owner_count):
                scan = changed(completed_scan(), 'core_rows', state='interrupted',
                               count=owner_count, count_precision='lower_bound')
                scan = replace(scan, findings=(corruption(
                    'core_rows', 'track_audio_orphan', owner_count + 1),))
                self.assert_sanitized(interrupted(scan))

    def test_orphan_prefix_does_not_excuse_another_impossible_group(self):
        for code in ROW_CODES['core_rows']:
            if code == 'track_audio_orphan':
                continue
            with self.subTest(code=code):
                scan = changed(completed_scan(), 'core_rows', state='interrupted',
                               count=0, count_precision='lower_bound')
                scan = replace(scan, findings=(
                    corruption('core_rows', 'track_audio_orphan', precision='lower_bound'),
                    corruption('core_rows', code, precision='lower_bound')))
                self.assert_sanitized(interrupted(scan))

    def test_completed_relational_graph_findings_also_require_exact_precision(self):
        for owner in ('current_graph', 'historical_graph'):
            for code in ('graph_counts_invalid', 'graph_pointer_invalid', 'graph_mirror_invalid'):
                with self.subTest(owner=owner, code=code):
                    scan = changed(completed_scan(), owner, count=1)
                    self.assert_sanitized(replace(scan, findings=(
                        corruption(owner, code, precision='lower_bound'),)))

    def test_multiple_codes_on_same_row_are_not_summed(self):
        for owner, codes in ROW_CODES.items():
            with self.subTest(owner=owner):
                scan = changed(completed_scan(), owner, count=1)
                scan = replace(scan, findings=tuple(corruption(owner, code) for code in codes))
                report = execute(scan)
                self.assertEqual((report.schema_version, report.status, report.exit_code, report.complete),
                                 (10, 'corrupt', 1, True))
                self.assertEqual(report.checks, scan.checks)
                self.assertEqual(set(report.findings), set(scan.findings))

    def test_interrupted_lower_bounds_remain_valid_without_summing_groups(self):
        for owner, codes in ROW_CODES.items():
            with self.subTest(owner=owner):
                scan = changed(completed_scan(), owner, state='interrupted', count=1,
                               count_precision='lower_bound')
                scan = replace(scan, findings=tuple(corruption(owner, code, precision='lower_bound')
                                                    for code in codes))
                scan = interrupted(scan)
                report = execute(scan)
                self.assertEqual((report.schema_version, report.stop_reason, report.exit_code, report.complete),
                                 (10, 'read_error', 4, False))
                self.assertEqual(report.checks, scan.checks)
                self.assertEqual(set(report.findings), set(scan.findings))

    def test_relational_graph_groups_are_not_misclassified_as_row_bounded(self):
        # Current positioned descriptor checks and mirror/pointer relations do
        # not correspond one-to-one to the namespace's semantic row meter.
        for code in ('graph_counts_invalid', 'graph_pointer_invalid', 'graph_mirror_invalid'):
            with self.subTest(code=code):
                scan = changed(completed_scan(), 'current_graph', count=1)
                scan = replace(scan, findings=(corruption('current_graph', code, 2),))
                report = execute(scan)
                self.assertEqual((report.schema_version, report.exit_code, report.complete), (10, 1, True))
                self.assertEqual(report.findings, scan.findings)

    def test_completed_exact_corruption_survives_cleanup_and_cancel_precedence(self):
        for reason, codes, exit_code in (
                ('read_error', ('read_failed',), 4),
                ('cleanup_error', ('read_failed', 'cleanup_failed'), 4),
                ('cancelled', ('read_failed', 'cleanup_failed', 'cancelled'), 130)):
            for owner in ('core_rows', 'current_graph', 'historical_graph', 'current_evidence'):
                with self.subTest(reason=reason, owner=owner):
                    scan = changed(completed_scan(), owner, count=1)
                    scan = replace(scan, findings=(corruption(owner, ROW_CODES[owner][0]),))
                    scan = interrupted(scan, reason, codes)
                    report = execute(scan)
                    self.assertEqual((report.schema_version, report.stop_reason, report.exit_code),
                                     (10, reason, exit_code))
                    self.assertEqual(report.checks, scan.checks)
                    self.assertEqual(set(report.findings), set(scan.findings))

    def test_completed_owner_precision_is_required_even_after_late_cleanup_failure(self):
        scan = changed(completed_scan(), 'core_rows', count=1)
        scan = replace(scan, findings=(corruption('core_rows', 'track_size_invalid',
                                                precision='lower_bound'),))
        self.assert_sanitized(interrupted(scan, 'cleanup_error', ('cleanup_failed',)))


if __name__ == '__main__':
    unittest.main()
