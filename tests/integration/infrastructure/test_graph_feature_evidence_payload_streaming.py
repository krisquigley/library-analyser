import os
import resource
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from music_analyzer.infrastructure.persistence.explorer_readonly import ReadOnlyExplorerSQLiteRepository as AnalyzerReadOnlyExplorer
from music_explorer.infrastructure.explorer_readonly import ReadOnlyExplorerSQLiteRepository as StandaloneReadOnlyExplorer


_MEMORY_LIMIT_BYTES = 256 * 1024 * 1024
_PAYLOAD_BYTES = 2 * 1024 * 1024
_ROW_COUNT = 80
_TIMEOUT_SECONDS = 20


def _skip_without_posix_address_space_limit():
    if os.name != 'posix' or not hasattr(resource, 'RLIMIT_AS'):
        raise unittest.SkipTest('POSIX RLIMIT_AS is required for deterministic low-memory payload streaming coverage')


def _create_evidence_database(path: Path) -> tuple[tuple[str, str], ...]:
    identities = []
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA journal_mode=OFF')
        db.execute('''CREATE TABLE graph_feature_evidence(
            track_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            is_current INTEGER NOT NULL CHECK(is_current IN (0,1)),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(track_id,run_id))''')
        db.execute('CREATE INDEX idx_graph_feature_evidence_run_id ON graph_feature_evidence(run_id)')
        payload = 'x' * _PAYLOAD_BYTES
        for index in range(_ROW_COUNT):
            track_id = f'track-{index:04d}'
            run_id = f'run-{index:04d}'
            identities.append((track_id, run_id))
            db.execute(
                'INSERT INTO graph_feature_evidence(track_id,run_id,fingerprint,evidence_json,is_current) '
                'VALUES(?,?,?,?,1)',
                (track_id, run_id, f'{index:064x}', payload),
            )
    return tuple(identities)


def _run_limited_python(script: str, db_path: Path, *args: str) -> subprocess.CompletedProcess:
    command = 'ulimit -c 0; exec timeout -s KILL "$1" "$2" -c "$3" "$4" "$5" "${@:6}"'
    return subprocess.run(
        ['bash', '-lc', command, 'bash', str(_TIMEOUT_SECONDS), sys.executable, script, str(db_path), str(_MEMORY_LIMIT_BYTES), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=_TIMEOUT_SECONDS + 5,
    )


_ORDER_BY_BASELINE_SCRIPT = r'''
import resource
import sqlite3
import sys

path = sys.argv[1]
limit = int(sys.argv[2])
resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
try:
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA temp_store=MEMORY')
        identities = tuple(db.execute('SELECT track_id,run_id FROM graph_feature_evidence'))
        placeholders = ','.join('(?,?)' for _ in identities)
        parameters = tuple(value for identity in identities for value in identity)
        sql = (
            'SELECT track_id,run_id,evidence_json FROM graph_feature_evidence '
            f'WHERE is_current=1 AND (track_id,run_id) IN ({placeholders}) '
            'ORDER BY track_id,run_id'
        )
        plan = tuple(row[3] for row in db.execute('EXPLAIN QUERY PLAN ' + sql, parameters))
        print('\n'.join(plan))
        cursor = db.execute(sql, parameters)
        count = 0
        for _track_id, _run_id, _payload in cursor:
            count += 1
except MemoryError:
    print('MemoryError', file=sys.stderr)
    raise SystemExit(73)
print(f'rows={count}')
'''


_REPOSITORY_STREAM_SCRIPT = r'''
import importlib
import resource
import sqlite3
import sys

path = sys.argv[1]
limit = int(sys.argv[2])
module_name = sys.argv[3]
class_name = sys.argv[4]
Repository = getattr(importlib.import_module(module_name), class_name)
with sqlite3.connect(path) as db:
    identities = tuple(db.execute('SELECT track_id,run_id FROM graph_feature_evidence'))
resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
repo = Repository(path)
seen = {}
try:
    with sqlite3.connect(path) as db:
        for chunk in repo._iter_graph_feature_evidence_payload_chunks(db, tuple(reversed(identities)), current_only=True):
            for track_id, run_id, payload in chunk:
                if (track_id, run_id) in seen:
                    raise SystemExit(f'duplicate payload row: {(track_id, run_id)!r}')
                if len(payload) != 2 * 1024 * 1024:
                    raise SystemExit(f'unexpected payload length for {(track_id, run_id)!r}: {len(payload)}')
                seen[(track_id, run_id)] = len(payload)
except MemoryError:
    print('MemoryError', file=sys.stderr)
    raise SystemExit(73)
if set(seen) != set(identities):
    raise SystemExit(f'mismatched identities: missing={set(identities)-set(seen)} extra={set(seen)-set(identities)}')
print(len(seen))
'''


class _RecordingCursor:
    def __init__(self, rows):
        self._rows = rows
        self.closed = False

    def __iter__(self):
        return iter(self._rows)

    def close(self):
        self.closed = True


class _RecordingDb:
    def __init__(self, rows):
        self.rows = rows
        self.statements = []
        self.cursors = []

    def execute(self, sql, parameters=()):
        self.statements.append((sql, parameters))
        cursor = _RecordingCursor(self.rows)
        self.cursors.append(cursor)
        return cursor


class GraphFeatureEvidencePayloadStreamingTests(unittest.TestCase):
    def test_payload_chunk_query_does_not_request_sql_ordering_in_analyzer_and_standalone_mirrors(self):
        identities = (('track-b', 'run-b'), ('track-a', 'run-a'))
        rows = (('track-a', 'run-a', 'payload-a'), ('track-b', 'run-b', 'payload-b'))
        for repository_class in (AnalyzerReadOnlyExplorer, StandaloneReadOnlyExplorer):
            with self.subTest(repository=repository_class.__module__):
                db = _RecordingDb(rows)
                repo = object.__new__(repository_class)

                chunks = tuple(repo._iter_graph_feature_evidence_payload_chunks(db, identities, current_only=True))
                loaded = {
                    (track_id, run_id): payload
                    for chunk in chunks
                    for track_id, run_id, payload in chunk
                }

                self.assertEqual(loaded, {('track-a', 'run-a'): 'payload-a', ('track-b', 'run-b'): 'payload-b'})
                self.assertEqual(db.cursors[0].closed, True)
                normalized_sql = ' '.join(db.statements[0][0].split()).upper()
                self.assertNotIn('ORDER BY', normalized_sql)
                self.assertIn('(TRACK_ID,RUN_ID) IN', normalized_sql)
                self.assertEqual(len(db.statements[0][1]), 4)

    def test_sqlite_order_by_baseline_fails_but_mirrored_payload_iterators_stream_under_low_address_space(self):
        _skip_without_posix_address_space_limit()
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / 'analysis.sqlite'
            _create_evidence_database(db_path)

            baseline = _run_limited_python(_ORDER_BY_BASELINE_SCRIPT, db_path)
            self.assertEqual(
                baseline.returncode,
                0,
                f'ORDER BY baseline probe should complete or report a controlled MemoryError under '
                f'{_MEMORY_LIMIT_BYTES // (1024 * 1024)}MiB RLIMIT_AS; '
                f'stdout={baseline.stdout!r} stderr={baseline.stderr!r}',
            )
            self.assertIn('USE TEMP B-TREE FOR ORDER BY', baseline.stdout)
            self.assertIn(f'rows={_ROW_COUNT}', baseline.stdout)

            mirrors = (
                ('music_analyzer.infrastructure.persistence.explorer_readonly', 'ReadOnlyExplorerSQLiteRepository'),
                ('music_explorer.infrastructure.explorer_readonly', 'ReadOnlyExplorerSQLiteRepository'),
            )
            for module_name, class_name in mirrors:
                with self.subTest(repository=module_name):
                    streamed = _run_limited_python(_REPOSITORY_STREAM_SCRIPT, db_path, module_name, class_name)
                    self.assertEqual(
                        streamed.returncode,
                        0,
                        f'{module_name} should stream payloads under {_MEMORY_LIMIT_BYTES // (1024 * 1024)}MiB RLIMIT_AS; '
                        f'stdout={streamed.stdout!r} stderr={streamed.stderr!r}',
                    )
                    self.assertEqual(streamed.stdout.strip(), str(_ROW_COUNT))
                    self.assertNotIn('MemoryError', streamed.stderr)


if __name__ == '__main__':
    unittest.main()
