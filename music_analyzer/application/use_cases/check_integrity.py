"""Non-certifying report policy and validation of the diagnostic output port."""
from music_analyzer.application.dto.integrity import (
    IntegrityCheck, IntegrityFinding, IntegrityReport, IntegrityScan,
)
from music_analyzer.application.ports.integrity import IntegrityScanner


CHECKS = (
    ('compatibility', 'databases', 6), ('schema', 'schema_descriptors', 6),
    ('core_rows', 'rows', 6), ('metadata', 'rows', 6), ('retained_stages', 'rows', 6),
    ('current_graph', 'rows', 7), ('historical_graph', 'rows', 7),
    ('current_evidence', 'rows', 9), ('historical_evidence', 'rows', 9),
    ('sqlite_physical', 'physical_records', 6), ('sqlite_foreign_keys', 'foreign_key_records', 6),
    ('resource_access', 'databases', 6),
)
CODES = {
    'compatibility': ('application_id_mismatch', 'schema_version_unsupported'),
    'schema': ('schema_object_set_mismatch', 'schema_view_mismatch', 'schema_columns_mismatch',
               'schema_foreign_keys_mismatch', 'schema_unique_indexes_mismatch', 'schema_checks_mismatch'),
    'core_rows': ('track_identity_invalid', 'track_digest_invalid', 'track_size_invalid',
                  'track_audio_missing', 'track_audio_orphan', 'track_audio_duration_invalid', 'track_audio_policy_invalid'),
    'current_graph': ('graph_lifecycle_invalid', 'graph_counts_invalid', 'graph_pointer_invalid',
                      'graph_mirror_invalid', 'graph_edge_invalid'),
    'historical_graph': ('graph_lifecycle_invalid', 'graph_counts_invalid', 'graph_pointer_invalid',
                         'graph_mirror_invalid', 'graph_edge_invalid'),
    'resource_access': ('initial_access_failed', 'read_failed', 'cleanup_failed', 'deadline_exceeded',
                        'cancelled', 'row_limit_reached', 'utf8_limit_reached', 'value_limit_reached', 'finding_limit_reached'),
}
STOPS = ('scope_not_implemented', 'unsupported_database', 'unreadable_database', 'schema_blocked',
         'deadline', 'row_limit', 'utf8_limit', 'value_limit', 'finding_limit', 'read_error', 'cleanup_error', 'cancelled')
SELECTED = ('compatibility', 'schema', 'core_rows', 'current_graph', 'historical_graph', 'resource_access')
OPERATIONAL_STOPS = {
    'unreadable_database': 'initial_access_failed', 'read_error': 'read_failed',
    'cleanup_error': 'cleanup_failed', 'deadline': 'deadline_exceeded',
    'cancelled': 'cancelled', 'row_limit': 'row_limit_reached',
    'utf8_limit': 'utf8_limit_reached', 'value_limit': 'value_limit_reached',
    'finding_limit': 'finding_limit_reached',
}


def _operationally_consistent(scan, resource):
    causes = {item.code for item in scan.findings if item.check_id == 'resource_access'}
    # At capacity the finding-limit stop need not admit an extra operational group.
    if scan.findings_truncated:
        if 'finding_limit_reached' not in causes and len(scan.findings) != 100:
            return False
        causes.add('finding_limit_reached')
        if scan.stop_reason not in ('finding_limit', 'cleanup_error', 'cancelled'):
            return False
    if scan.supported and 'initial_access_failed' in causes:
        return False
    if causes:
        if resource.state == 'completed' or scan.implemented_scope_complete:
            return False
        # Group inventory order carries no event chronology. Only these two
        # overrides are unconditional; ordinary stops must match a retained cause.
        if 'cancelled' in causes:
            return scan.stop_reason == 'cancelled'
        if 'cleanup_failed' in causes:
            return scan.stop_reason == 'cleanup_error'
        return OPERATIONAL_STOPS.get(scan.stop_reason) in causes
    return (resource.state == 'completed'
            and scan.stop_reason in ('scope_not_implemented', 'schema_blocked', 'unsupported_database'))


def _count_valid(count):
    return type(count) is int and 0 <= count <= 2_000_000


def _valid(scan):
    if type(scan) is not IntegrityScan:
        return False
    if (type(scan.supported) is not bool or type(scan.implemented_scope_complete) is not bool
            or type(scan.findings_truncated) is not bool or type(scan.stop_reason) is not str
            or scan.stop_reason not in STOPS):
        return False
    version = scan.schema_version
    if version is not None and (type(version) is not int or version not in (6, 7, 8, 9, 10)):
        return False
    if scan.supported != (version is not None):
        return False
    if type(scan.checks) is not tuple or len(scan.checks) != len(CHECKS):
        return False
    for item, (name, unit, first_version) in zip(scan.checks, CHECKS):
        if type(item) is not IntegrityCheck:
            return False
        if (type(item.check_id) is not str or item.check_id != name
                or type(item.category) is not str or item.category != name
                or type(item.count_unit) is not str or item.count_unit != unit
                or type(item.state) is not str or type(item.count_precision) is not str):
            return False
        if item.state in ('completed', 'interrupted'):
            if not _count_valid(item.count) or item.count_precision != ('exact' if item.state == 'completed' else 'lower_bound'):
                return False
        elif item.state in ('blocked', 'not_implemented', 'not_applicable'):
            if item.count is not None or item.count_precision != 'unavailable':
                return False
        else:
            return False
        if name not in SELECTED:
            expected = 'blocked' if version is None else ('not_applicable' if version < first_version else 'not_implemented')
            if item.state != expected:
                return False
        elif name in ('current_graph', 'historical_graph') and version is not None and version < first_version:
            if item.state != 'not_applicable':
                return False
        elif item.state not in ('completed', 'interrupted', 'blocked'):
            return False
        if version is None and name in ('schema', 'core_rows', 'current_graph', 'historical_graph') and item.state != 'blocked':
            return False
    if type(scan.findings) is not tuple or len(scan.findings) > 100:
        return False
    keys = set()
    for item in scan.findings:
        if type(item) is not IntegrityFinding:
            return False
        if (type(item.check_id) is not str or item.check_id not in CODES
                or type(item.code) is not str or item.code not in CODES[item.check_id]
                or type(item.severity) is not str or type(item.count_unit) is not str
                or item.count_unit != 'occurrences' or not _count_valid(item.count)
                or type(item.count_precision) is not str or item.count_precision not in ('exact', 'lower_bound')):
            return False
        severity = 'compatibility' if item.check_id == 'compatibility' else ('operational' if item.check_id == 'resource_access' else 'corruption')
        key = (item.check_id, item.code)
        if item.severity != severity or key in keys:
            return False
        if version == 6 and item.check_id in ('current_graph', 'historical_graph'):
            return False
        keys.add(key)
    by_id = {item.check_id: item for item in scan.checks}
    for name in ('compatibility', 'resource_access'):
        item = by_id[name]
        if item.state == 'completed' and item.count != 1:
            return False
        if item.state == 'interrupted' and item.count != 0:
            return False
    compatibility_failed = any(item.check_id == 'compatibility' for item in scan.findings)
    schema_failed = any(item.check_id == 'schema' for item in scan.findings)
    if not _operationally_consistent(scan, by_id['resource_access']):
        return False
    if scan.stop_reason == 'unsupported_database' and (
            by_id['compatibility'].state != 'completed' or not compatibility_failed
            or any(item.check_id != 'compatibility' for item in scan.findings)):
        return False
    if scan.stop_reason == 'schema_blocked' and (
            version is None or not schema_failed
            or by_id['schema'].state not in ('completed', 'blocked')
            or by_id['core_rows'].state != 'blocked'):
        return False
    if version is not None and (by_id['compatibility'].state != 'completed' or compatibility_failed
                                or scan.stop_reason in ('unsupported_database', 'unreadable_database')):
        return False
    if by_id['schema'].state != 'completed' or schema_failed:
        if by_id['core_rows'].state != 'blocked':
            return False
        if version is not None and version >= 7 and any(
                by_id[name].state != 'blocked' for name in ('current_graph', 'historical_graph')):
            return False
    if scan.stop_reason == 'scope_not_implemented' and (
            version is None or compatibility_failed or schema_failed
            or any(by_id[name].state not in ('completed', 'not_applicable') for name in SELECTED)):
        return False
    selected_complete = (version is not None and scan.stop_reason == 'scope_not_implemented'
                         and all(item.state in ('completed', 'not_applicable') for item in scan.checks if item.check_id in SELECTED)
                         and not any(item.check_id == 'schema' for item in scan.findings))
    return scan.implemented_scope_complete == selected_complete


def _fallback(reason):
    checks = tuple(IntegrityCheck(name, name, 'interrupted' if name == 'resource_access' else 'blocked',
                                  0 if name == 'resource_access' else None, unit,
                                  'lower_bound' if name == 'resource_access' else 'unavailable')
                   for name, unit, first_version in CHECKS)
    code = 'cancelled' if reason == 'cancelled' else 'read_failed'
    return IntegrityScan(checks=checks, findings=(IntegrityFinding('resource_access', code, 'operational', 1),),
                         stop_reason=reason, supported=False)


def _report(scan):
    exit_code = 130 if scan.stop_reason == 'cancelled' else (3 if scan.stop_reason in ('unsupported_database', 'unreadable_database') else 4)
    order = {name: index for index, (name, unit, first_version) in enumerate(CHECKS)}
    findings = tuple(sorted(scan.findings, key=lambda item: (order[item.check_id], CODES[item.check_id].index(item.code))))
    return IntegrityReport(scan.schema_version, 'unsupported' if exit_code == 3 else 'incomplete',
                           scan.implemented_scope_complete, scan.stop_reason, exit_code,
                           scan.checks, findings, scan.findings_truncated)


class CheckIntegrity:
    def __init__(self, scanner: IntegrityScanner):
        self.scanner = scanner

    def execute(self, database: str, deadline_seconds: float = 120) -> IntegrityReport:
        try:
            scan = self.scanner.scan(database, deadline_seconds)
            if not _valid(scan):
                scan = _fallback('read_error')
        except KeyboardInterrupt:
            scan = _fallback('cancelled')
        except Exception:
            # Port failures cannot expose a target, statement, payload or traceback.
            scan = _fallback('read_error')
        return _report(scan)
