"""Dedicated read-only LIMITED diagnostic adapter; never constructs a writer."""
from pathlib import Path
from math import isfinite
from itertools import zip_longest
import re
import sqlite3
from time import monotonic
import sys

from music_analyzer.domain.library_duration_policy import DurationVerification, TRUSTED_DURATION_SOURCES, active_library_duration_policy

from music_analyzer.application.dto.integrity import IntegrityCheck, IntegrityFinding, IntegrityScan
from music_analyzer.infrastructure.persistence import integrity_schema as contract

MAX_ROWS = 1_000_000
MAX_UTF8_BYTES = 1 << 30
MAX_VALUE_BYTES = 32 << 20
MAX_GROUPS = 100


class AdmissionStop(Exception):
    def __init__(self, reason):
        self.reason = reason


class Delivery:
    """Preflight scalar sizes before delivering any input-sized Python value."""
    def __init__(self, connection, deadline):
        self.connection = connection
        self.deadline = deadline
        self.interrupted = None
        self.first_error = None
        self.core_count = 0
        self.core_counts = {}
        self.schema_findings = []
        self.schema_inventory_exhausted = False
        self.group_keys = set()
        self.findings_truncated = False
        self.cursor_cleanup_failed = False
        self.cursor_cancelled = False
        self.count = 0
        self.utf8_bytes = 0
        self.schema_count = 0
        self.encoding_factor = 1
        self.encoding = 'UTF-8'
        self.evidence_work = {}
        self.evidence_findings = {}
        self.graph_work = {}
        self.graph_findings = {}

    def claim_group(self, check_id, code):
        key = (check_id, code)
        if key not in self.group_keys:
            if len(self.group_keys) >= MAX_GROUPS:
                self.findings_truncated = True
                raise AdmissionStop('finding_limit')
            self.group_keys.add(key)

    def record_schema(self, target, code, count=1):
        self.claim_group('schema', code)
        target.append(finding('schema', code, count))

    def record_core(self, counts, code):
        self.claim_group('core_rows', code)
        counts[code] += 1

    def close_all(self, *cursors):
        # Preserve an active read/limit/interrupt cause while attempting every close.
        active_error = sys.exc_info()[0] is not None
        for cursor in cursors:
            if cursor is None:
                continue
            try:
                cursor.close()
            except KeyboardInterrupt:
                self.cursor_cancelled = True
            except (sqlite3.Error, OSError):
                self.cursor_cleanup_failed = True
        if not active_error:
            self.guard()

    def guard(self):
        if self.cursor_cancelled:
            raise KeyboardInterrupt
        if self.cursor_cleanup_failed:
            raise AdmissionStop('cleanup_error')
        if monotonic() >= self.deadline:
            self.interrupted = 'deadline'
            raise AdmissionStop('deadline')

    def progress(self):
        if monotonic() >= self.deadline:
            self.interrupted = 'deadline'
            return 1
        return 0

    def observe_error(self):
        # Keep only timing/category, before cursor finally blocks can delay or
        # interrupt propagation. Never retain an exception or input value.
        if self.first_error is None:
            self.first_error = (monotonic(), self.interrupted)

    def execute(self, sql, params=()):
        self.guard()
        remaining_ms = max(0, int((self.deadline - monotonic()) * 1000))
        try:
            self.close_all(self.connection.execute(f'PRAGMA busy_timeout={remaining_ms}'))
            self.guard()
            return self.connection.execute(sql, params)
        except (sqlite3.Error, OSError, UnicodeError):
            self.observe_error()
            raise

    def one(self, cursor):
        self.guard()
        if self.count >= MAX_ROWS:
            raise AdmissionStop('row_limit')
        try:
            row = cursor.fetchone()
        except (sqlite3.Error, OSError, UnicodeError):
            self.observe_error()
            raise
        if row is not None:
            self.count += 1
        self.guard()
        return row

    def rows(self, sql, columns, params=(), *, descriptor=False):
        # SQL and column expressions originate only in this adapter's fixed queries.
        sizes = ','.join(
            f"CASE typeof({column}) WHEN 'text' THEN length(CAST({column} AS BLOB)) "
            f"WHEN 'blob' THEN -1-length({column}) ELSE NULL END" for column in columns)
        preflight = self.execute(f'SELECT {sizes} FROM ({sql})', params)
        values = None
        try:
            while (lengths := self.one(preflight)) is not None:
                upper_bytes = 0
                for length in lengths:
                    if length is None:
                        continue
                    bound = length * self.encoding_factor if length >= 0 else -1 - length
                    if bound > MAX_VALUE_BYTES:
                        raise AdmissionStop('value_limit')
                    if length >= 0:
                        upper_bytes += bound
                if upper_bytes > MAX_UTF8_BYTES - self.utf8_bytes:
                    raise AdmissionStop('utf8_limit')
                if values is None:
                    values = self.execute(sql, params)
                row = self.one(values)
                if row is None:
                    raise sqlite3.DatabaseError('delivery mismatch')
                for value in row:
                    if isinstance(value, str):
                        self.utf8_bytes += len(value.encode('utf-8'))
                if descriptor:
                    self.schema_count += 1
                yield row
        except (sqlite3.Error, OSError, UnicodeError):
            self.observe_error()
            raise
        finally:
            self.close_all(preflight, values)

    def scalar(self, sql, columns, params=()):
        rows = self.rows(sql, columns, params)
        try:
            return next(rows)[0]
        finally:
            rows.close()

    def descriptors(self, sql, columns, maximum, params=()):
        result = []
        excess = False
        rows = self.rows(sql, columns, params, descriptor=True)
        try:
            for row in rows:
                if len(result) >= maximum:
                    excess = True
                else:
                    result.append(row)
            return None if excess else result
        finally:
            rows.close()


def check(check_id, state, count, unit):
    precision = 'exact' if state == 'completed' else ('lower_bound' if state == 'interrupted' else 'unavailable')
    return IntegrityCheck(check_id, check_id, state, count, unit, precision)


def finding(check_id, code, count=1, precision='exact'):
    severity = 'compatibility' if check_id == 'compatibility' else ('operational' if check_id == 'resource_access' else 'corruption')
    return IntegrityFinding(check_id, code, severity, count, count_precision=precision)


class SQLiteIntegrityScanner:
    def scan(self, database: str, deadline_seconds: float = 120) -> IntegrityScan:
        if (isinstance(deadline_seconds, bool) or not isinstance(deadline_seconds, (int, float))
                or not isfinite(deadline_seconds) or not 0 < deadline_seconds <= 120):
            raise ValueError('Invalid audit deadline')
        deadline = monotonic() + deadline_seconds
        connection = None
        version = None
        delivery = None
        compatibility_complete = False
        schema_check = check('schema', 'blocked', None, 'schema_descriptors')
        core_check = check('core_rows', 'blocked', None, 'rows')
        graph_checks = {}
        evidence_checks = {}
        findings = []
        stop = 'scope_not_implemented'
        phase = 'compatibility'
        access_started = False
        try:
            if monotonic() >= deadline:
                raise AdmissionStop('deadline')
            if '\x00' in str(database):
                raise OSError('Invalid target')
            access_started = True
            connection = sqlite3.connect(Path(database).absolute().as_uri() + '?mode=ro', uri=True,
                                         timeout=max(0, deadline - monotonic()))
            delivery = Delivery(connection, deadline)
            connection.set_progress_handler(delivery.progress, 1000)
            delivery.close_all(delivery.execute('PRAGMA query_only=ON'))
            delivery.close_all(delivery.execute('BEGIN'))
            first = delivery.execute('SELECT 1 FROM sqlite_master LIMIT 1')
            try:
                delivery.one(first)
            finally:
                delivery.close_all(first)
            app = delivery.scalar('SELECT application_id FROM pragma_application_id', ('application_id',))
            literal_version = delivery.scalar('SELECT user_version FROM pragma_user_version', ('user_version',))
            compatibility_complete = True
            if app != 0x4D414E41:
                findings.append(finding('compatibility', 'application_id_mismatch'))
            if literal_version not in (6, 7, 8, 9, 10):
                findings.append(finding('compatibility', 'schema_version_unsupported'))
            if findings:
                stop = 'unsupported_database'
            else:
                version = literal_version
                encoding = delivery.scalar('SELECT encoding FROM pragma_encoding', ('encoding',))
                delivery.encoding = encoding
                delivery.encoding_factor = 1 if encoding == 'UTF-8' else 2
                phase = 'schema'
                schema_check, schema_findings = self._schema(delivery, version)
                findings.extend(schema_findings)
                if schema_findings:
                    stop = 'schema_blocked'
                else:
                    phase = 'core_rows'
                    core_check, core_findings = self._core(delivery)
                    findings.extend(core_findings)
                    if version >= 7:
                        for owner in ('current_graph', 'historical_graph'):
                            phase = owner
                            graph_checks[owner], graph_findings = self._graph(delivery, version, owner)
                            findings.extend(graph_findings)
                    if version >= 9:
                        from music_analyzer.infrastructure.persistence.integrity_evidence import scan_evidence
                        for owner in ('current_evidence', 'historical_evidence'):
                            phase = owner
                            evidence_checks[owner], evidence_findings = scan_evidence(delivery, owner)
                            findings.extend(evidence_findings)
        except AdmissionStop as error:
            stop = error.reason
        except KeyboardInterrupt:
            stop = 'cancelled'
        except (sqlite3.Error, OSError, UnicodeError):
            # Delivery observes errors before its paired cursor cleanup; initial
            # connection errors have no Delivery and are sampled here.
            error_at, interrupted_at = (delivery.first_error if delivery and delivery.first_error
                                        else (monotonic(), delivery.interrupted if delivery else None))
            if error_at >= deadline:
                stop = 'deadline'
            else:
                stop = interrupted_at or ('read_error' if version else 'unreadable_database')
        finally:
            earlier_stop = stop
            cleanup_failed = bool(delivery and delivery.cursor_cleanup_failed)
            if delivery and delivery.cursor_cancelled:
                stop = 'cancelled'
            if connection is not None:
                for operation in (lambda: connection.set_progress_handler(None, 0), connection.close):
                    try:
                        operation()
                    except KeyboardInterrupt:
                        stop = 'cancelled'
                    except (sqlite3.Error, OSError):
                        cleanup_failed = True
            if cleanup_failed:
                findings.append(finding('resource_access', 'cleanup_failed', precision='lower_bound'))
                if stop != 'cancelled':
                    stop = 'cleanup_error'
            if monotonic() >= deadline and stop in ('scope_not_implemented', 'schema_blocked', 'unsupported_database'):
                stop = 'deadline'
        operational = {
            'deadline': 'deadline_exceeded', 'row_limit': 'row_limit_reached',
            'utf8_limit': 'utf8_limit_reached', 'value_limit': 'value_limit_reached',
            'read_error': 'read_failed', 'unreadable_database': 'initial_access_failed',
            'cancelled': 'cancelled',
        }
        if earlier_stop in operational:
            findings.append(finding('resource_access', operational[earlier_stop], precision='lower_bound'))
        if stop in operational and stop != earlier_stop:
            findings.append(finding('resource_access', operational[stop], precision='lower_bound'))
        interrupted = stop not in ('scope_not_implemented', 'schema_blocked', 'unsupported_database')
        if interrupted and version and delivery:
            if phase == 'schema' and schema_check.state == 'blocked':
                schema_check = check('schema', 'interrupted', delivery.schema_count, 'schema_descriptors')
                findings.extend(finding('schema', item.code, item.count,
                                        'exact' if item.code == 'schema_object_set_mismatch'
                                        and delivery.schema_inventory_exhausted else 'lower_bound')
                                for item in delivery.schema_findings)
            if phase == 'core_rows' and core_check.state == 'blocked':
                core_check = check('core_rows', 'interrupted', delivery.core_count, 'rows')
                findings.extend(finding('core_rows', code, count, 'lower_bound') for code, count in delivery.core_counts.items() if count)
            if phase in ('current_graph', 'historical_graph') and phase not in graph_checks:
                graph_checks[phase] = check(phase, 'interrupted', delivery.graph_work.get(phase, 0), 'rows')
                findings.extend(finding(phase, code, count, 'lower_bound')
                                for code, count in delivery.graph_findings.get(phase, {}).items())
            if phase in ('current_evidence', 'historical_evidence') and phase not in evidence_checks:
                evidence_checks[phase] = check(phase, 'interrupted', delivery.evidence_work.get(phase, 0), 'rows')
                findings.extend(finding(phase, code, count, 'lower_bound')
                                for code, count in delivery.evidence_findings.get(phase, {}).items())
        compatibility_check = check('compatibility', 'completed', 1, 'databases') if compatibility_complete else check(
            'compatibility', 'interrupted' if access_started else 'blocked', 0 if access_started else None, 'databases')
        resource_check = check('resource_access', 'completed', 1, 'databases') if not interrupted else check(
            'resource_access', 'interrupted' if access_started else 'blocked', 0 if access_started else None, 'databases')
        checks = [compatibility_check, schema_check, core_check]
        for check_id, unit, first_version in (
                ('metadata', 'rows', 6), ('retained_stages', 'rows', 6),
                ('current_graph', 'rows', 7), ('historical_graph', 'rows', 7),
                ('current_evidence', 'rows', 9), ('historical_evidence', 'rows', 9),
                ('sqlite_physical', 'physical_records', 6), ('sqlite_foreign_keys', 'foreign_key_records', 6)):
            state = 'blocked' if version is None else ('not_applicable' if version < first_version else 'not_implemented')
            if check_id in ('current_graph', 'historical_graph', 'current_evidence', 'historical_evidence') and state == 'not_implemented':
                state = 'blocked'
            checks.append(evidence_checks.get(check_id, graph_checks.get(check_id, check(check_id, state, None, unit))))
        checks.append(resource_check)
        # Bounded fixed predicate groups; never retain row identities or samples.
        order = {item.check_id: index for index, item in enumerate(checks)}
        codes = ('application_id_mismatch', 'schema_version_unsupported', 'schema_object_set_mismatch',
                 'schema_view_mismatch', 'schema_columns_mismatch', 'schema_foreign_keys_mismatch',
                 'schema_unique_indexes_mismatch', 'schema_checks_mismatch', 'track_identity_invalid',
                 'track_digest_invalid', 'track_size_invalid', 'track_audio_missing', 'track_audio_orphan',
                 'track_audio_duration_invalid', 'track_audio_policy_invalid', 'initial_access_failed',
                 'read_failed', 'cleanup_failed', 'deadline_exceeded', 'cancelled', 'row_limit_reached',
                 'utf8_limit_reached', 'value_limit_reached', 'graph_lifecycle_invalid',
                 'graph_counts_invalid', 'graph_pointer_invalid', 'graph_mirror_invalid', 'graph_edge_invalid')
        from music_analyzer.application.use_cases.integrity_evidence import EvidenceCode
        codes += tuple(code.value for code in EvidenceCode)
        grouped = {}
        for item in findings:
            key = (item.check_id, item.code)
            previous = grouped.get(key)
            if previous is None:
                grouped[key] = item
            else:
                precision = 'exact' if previous.count_precision == item.count_precision == 'exact' else 'lower_bound'
                grouped[key] = finding(item.check_id, item.code, previous.count + item.count, precision)
        findings = sorted(grouped.values(), key=lambda item: (order[item.check_id], codes.index(item.code)))
        truncated = bool(delivery and delivery.findings_truncated)
        if len(findings) > MAX_GROUPS:
            truncated = True
            if stop in ('scope_not_implemented', 'schema_blocked', 'unsupported_database'):
                stop = 'finding_limit'
            findings = findings[:MAX_GROUPS]
            checks[-1] = check('resource_access', 'interrupted' if access_started else 'blocked',
                               0 if access_started else None, 'databases')
        return IntegrityScan(schema_version=version, checks=tuple(checks), findings=tuple(findings),
                             supported=version is not None, stop_reason=stop, findings_truncated=truncated,
                             implemented_scope_complete=version is not None and stop == 'scope_not_implemented'
                             and schema_check.state == 'completed' and core_check.state == 'completed'
                             and (version < 7 or all(graph_checks.get(owner) is not None
                                  and graph_checks[owner].state == 'completed'
                                  for owner in ('current_graph', 'historical_graph')))
                             and (version < 9 or all(evidence_checks.get(owner) is not None
                                  and evidence_checks[owner].state == 'completed'
                                  for owner in ('current_evidence', 'historical_evidence'))))

    def _graph(self, delivery, version, owner):
        """Stream namespace-owned work; auxiliary lookups only charge admission.

        The established FULL-reader predicates are repeated here deliberately:
        diagnostics must exhaust invalid relations rather than fail on row one.
        Ordered paired streams avoid retaining input-sized mirrors or ID sets.
        """
        counts = {}
        delivery.graph_findings[owner] = counts
        delivery.graph_work[owner] = 0

        def record(code):
            delivery.claim_group(owner, code)
            counts[code] = counts.get(code, 0) + 1

        def work():
            delivery.graph_work[owner] += 1

        current = owner == 'current_graph'
        edge_columns = ('source_track_id', 'target_track_id', 'score', 'distance',
                        'supported_group_count', 'distance_policy_version', 'neighbour_policy_version')
        edge_list = ','.join(edge_columns)
        pointer = None
        if current:
            pointers = 0
            for build_id, in delivery.rows('SELECT id FROM graph_builds WHERE is_current=1 ORDER BY id', ('id',)):
                pointers += 1
                pointer = build_id
            if pointers > 1:
                record('graph_pointer_invalid')

        build_columns = ('id', 'status', 'edge_count', 'sparse_k', 'distance_policy_version',
                         'neighbour_policy_version', 'is_current')
        where = ' WHERE is_current=1' if current else ''
        for build_id, status, declared, sparse_k, distance_policy, neighbour_policy, is_current in delivery.rows(
                f'SELECT {",".join(build_columns)} FROM graph_builds{where} ORDER BY id', build_columns):
            work()
            allowed = ('completed', 'failed') if version < 10 else ('building', 'completed', 'failed', 'interrupted')
            if (status not in allowed or not isinstance(sparse_k, int) or sparse_k < 0
                    or not isinstance(distance_policy, str) or not distance_policy
                    or not isinstance(neighbour_policy, str) or not neighbour_policy
                    or is_current not in (0, 1) or (status != 'completed' and is_current)):
                record('graph_lifecycle_invalid')
            actual = delivery.scalar('SELECT count(*) AS n FROM graph_build_edges WHERE build_id=?', ('n',), (build_id,))
            if (not isinstance(declared, int) or declared < 0
                    or (status == 'completed' and declared != actual)
                    or (status == 'failed' and actual != 0)):
                record('graph_counts_invalid')

        if version >= 8:
            # Current descriptors were already counted as the current build;
            # positioned descriptors are semantic work only in retained history.
            sql = 'SELECT build_id,edge_count FROM graph_build_positioned_snapshots'
            params = ()
            if current:
                sql += ' WHERE build_id=?'
                params = (pointer,)
            for build_id, declared in delivery.rows(sql + ' ORDER BY build_id', ('build_id', 'edge_count'), params):
                if not current:
                    work()
                actual = delivery.scalar('SELECT count(*) AS n FROM graph_build_positioned_edges WHERE build_id=?', ('n',), (build_id,))
                if not isinstance(declared, int) or declared < 0 or declared != actual:
                    record('graph_counts_invalid')

        tables = [('graph_edges', 'graph_build_edges')]
        if version >= 8:
            tables.append(('graph_positioned_edges', 'graph_build_positioned_edges'))
        for published, retained in tables:
            table = published if current else retained
            # Include the build ID in historical delivery, not just in SQL, so
            # late cursor errors preserve findings from the actual value stream.
            columns = edge_columns if current else ('build_id',) + edge_columns
            # Independent edge predicates need no ordering or hidden rowid.
            for row in delivery.rows(f'SELECT {",".join(columns)} FROM {table}', columns):
                work()
                source, target, score, distance, support, distance_policy, neighbour_policy = row[-7:]
                if (not isinstance(source, str) or not isinstance(target, str) or source >= target
                        or not isinstance(score, (int, float)) or not 0 <= score <= 1
                        or not isinstance(distance, (int, float)) or not 0 <= distance <= 1
                        or round(1 - distance, 6) != round(score, 6)
                        or not isinstance(support, int) or support <= 0
                        or not isinstance(distance_policy, str) or not distance_policy
                        or not isinstance(neighbour_policy, str) or not neighbour_policy):
                    record('graph_edge_invalid')
            if current:
                if pointer is None:
                    if delivery.scalar(f'SELECT count(*) AS n FROM {published}', ('n',)):
                        record('graph_pointer_invalid')
                else:
                    # Exhaust both ordered streams, even after a difference.
                    # Keep only one admitted row per side; do not materialize
                    # mirrors in Python or in an SQL EXCEPT temporary relation.
                    order = ' ORDER BY source_track_id,target_track_id'
                    left = delivery.rows(f'SELECT {edge_list} FROM {published}' + order, edge_columns)
                    right = delivery.rows(f'SELECT {edge_list} FROM {retained} WHERE build_id=?' + order,
                                          edge_columns, (pointer,))
                    unequal = False
                    try:
                        for published_row, retained_row in zip_longest(left, right):
                            if published_row != retained_row and not unequal:
                                record('graph_mirror_invalid')
                                unequal = True
                    finally:
                        try:
                            left.close()
                        finally:
                            right.close()
        return check(owner, 'completed', delivery.graph_work[owner], 'rows'), tuple(
            finding(owner, code, count) for code, count in counts.items())

    def _schema(self, delivery, version):
        schema = dict(contract._EXPECTED_SCHEMA)
        objects = {(name, 'table') for name in schema} | {(name, 'view') for name in contract._EXPECTED_VIEWS}
        for first_version, tables, indexes in (
                (7, contract._EXPECTED_GRAPH_SCHEMA if version >= 10 else contract._EXPECTED_GRAPH_SCHEMA_LEGACY, contract._EXPECTED_GRAPH_INDEXES),
                (8, contract._EXPECTED_POSITIONED_GRAPH_SCHEMA, contract._EXPECTED_POSITIONED_GRAPH_INDEXES),
                (9, contract._EXPECTED_GRAPH_FEATURE_SCHEMA, contract._EXPECTED_GRAPH_FEATURE_INDEXES)):
            if version >= first_version:
                schema.update(tables)
                objects |= {(name, 'table') for name in tables} | indexes
        seen = set()
        unexpected = 0
        findings = []
        delivery.schema_findings = findings
        for pair in delivery.rows("SELECT name,type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' AND type IN ('table','view','index') ORDER BY name,type", ('name', 'type'), descriptor=True):
            if pair in objects:
                seen.add(pair)
            else:
                unexpected += 1
                if unexpected == 1:
                    delivery.record_schema(findings, 'schema_object_set_mismatch')
                else:
                    findings[0] = finding('schema', 'schema_object_set_mismatch', unexpected, 'lower_bound')
        # Inventory precision is independent of the later descriptor families.
        delivery.schema_inventory_exhausted = True
        missing = objects - seen
        if unexpected:
            findings[0] = finding('schema', 'schema_object_set_mismatch', unexpected + len(missing))
        elif missing:
            delivery.record_schema(findings, 'schema_object_set_mismatch', len(missing))
        if missing:
            return check('schema', 'blocked', None, 'schema_descriptors'), findings
        for name, (columns, expected_sql) in contract._EXPECTED_VIEWS.items():
            descriptors = delivery.descriptors(f'SELECT name FROM pragma_table_info(\'{name}\') ORDER BY cid', ('name',), len(columns))
            sql = delivery.scalar("SELECT sql FROM sqlite_master WHERE type='view' AND name=?", ('sql',), (name,))
            normalize = lambda value: ' '.join(value.rstrip(';').split())
            if descriptors is None or tuple(row[0] for row in descriptors) != columns or normalize(sql) != normalize(expected_sql):
                delivery.record_schema(findings, 'schema_view_mismatch')
        for name, expected in schema.items():
            sql = delivery.scalar("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", ('sql',), (name,))
            columns = delivery.descriptors(f'SELECT name,type,"notnull",pk FROM pragma_table_info(\'{name}\') ORDER BY cid', ('name', 'type', '"notnull"', 'pk'), max(map(len, expected['columns'])))
            actual = None if columns is None else tuple((row[0], row[1].upper(), bool(row[2]), row[3]) for row in columns)
            if actual not in expected['columns']:
                delivery.record_schema(findings, 'schema_columns_mismatch')
            keys = delivery.descriptors(f'SELECT id,seq,"table","from","to" FROM pragma_foreign_key_list(\'{name}\') ORDER BY id,seq', ('id', 'seq', '"table"', '"from"', '"to"'), 32)
            grouped = {}
            if keys is not None:
                for key_id, sequence, target, source_column, target_column in keys:
                    grouped.setdefault(key_id, [target, [], []])
                    grouped[key_id][1].append(source_column)
                    grouped[key_id][2].append(target_column)
            actual_keys = None if keys is None else tuple(sorted((target, tuple(source), tuple(dest)) for target, source, dest in grouped.values()))
            if actual_keys not in expected['foreign_keys']:
                delivery.record_schema(findings, 'schema_foreign_keys_mismatch')
            indexes = delivery.descriptors(f'SELECT name,"unique",origin FROM pragma_index_list(\'{name}\') ORDER BY seq', ('name', '"unique"', 'origin'), 32)
            uniques = []
            if indexes is not None:
                for index_name, unique, origin in indexes:
                    if unique and origin == 'u':
                        info = delivery.descriptors('SELECT name FROM pragma_index_info(?) ORDER BY seqno', ('name',), 32, (index_name,))
                        if info is None:
                            indexes = None
                            break
                        uniques.append(tuple(row[0] for row in info))
            if indexes is None or tuple(sorted(uniques)) != expected['unique_indexes']:
                delivery.record_schema(findings, 'schema_unique_indexes_mismatch')
            compact = ' '.join(sql.split())
            if not any(all(required in compact for required in checks) for checks in expected['checks']):
                delivery.record_schema(findings, 'schema_checks_mismatch')
        # Stable inventory order, with equal-code groups accumulated once.
        codes = ('schema_object_set_mismatch', 'schema_view_mismatch', 'schema_columns_mismatch', 'schema_foreign_keys_mismatch', 'schema_unique_indexes_mismatch', 'schema_checks_mismatch')
        grouped_findings = tuple(finding('schema', code, sum(item.count for item in findings if item.code == code)) for code in codes if any(item.code == code for item in findings))
        return check('schema', 'completed', delivery.schema_count, 'schema_descriptors'), grouped_findings

    def _core(self, delivery):
        codes = ('track_identity_invalid', 'track_digest_invalid', 'track_size_invalid',
                 'track_audio_missing', 'track_audio_orphan', 'track_audio_duration_invalid', 'track_audio_policy_invalid')
        counts = dict.fromkeys(codes, 0)
        delivery.core_counts = counts
        row_count = 0
        for track_id, digest, size in delivery.rows('SELECT id,sha256,size FROM tracks ORDER BY rowid', ('id', 'sha256', 'size')):
            row_count += 1
            delivery.core_count += 1
            if not isinstance(track_id, str) or re.fullmatch(r'sha256:[0-9a-f]{64}', track_id) is None or track_id != f'sha256:{digest}':
                delivery.record_core(counts, 'track_identity_invalid')
            if not isinstance(digest, str) or re.fullmatch(r'[0-9a-f]{64}', digest) is None:
                delivery.record_core(counts, 'track_digest_invalid')
            if not isinstance(size, int) or size < 0:
                delivery.record_core(counts, 'track_size_invalid')
        for marker, in delivery.rows('SELECT 1 AS marker FROM tracks t LEFT JOIN track_audio a ON a.track_id=t.id WHERE a.track_id IS NULL ORDER BY t.rowid', ('marker',)):
            delivery.record_core(counts, 'track_audio_missing')
        for marker, in delivery.rows('SELECT 1 AS marker FROM track_audio a LEFT JOIN tracks t ON t.id=a.track_id WHERE t.id IS NULL ORDER BY a.rowid', ('marker',)):
            delivery.record_core(counts, 'track_audio_orphan')
        for duration, source, status, reason in delivery.rows('SELECT duration_seconds,duration_source,status,reason FROM track_audio ORDER BY rowid', ('duration_seconds', 'duration_source', 'status', 'reason')):
            row_count += 1
            delivery.core_count += 1
            if isinstance(duration, (int, float)) and not isinstance(duration, bool) and not isfinite(duration):
                delivery.record_core(counts, 'track_audio_duration_invalid')
            decision = active_library_duration_policy(DurationVerification(duration, source) if source else None)
            expected_status = 'eligible' if decision.active else ('excluded' if source in TRUSTED_DURATION_SOURCES and duration is not None else 'unknown')
            if status != expected_status or reason != (decision.warning or ''):
                delivery.record_core(counts, 'track_audio_policy_invalid')
        return check('core_rows', 'completed', row_count, 'rows'), tuple(finding('core_rows', code, counts[code]) for code in codes if counts[code])
