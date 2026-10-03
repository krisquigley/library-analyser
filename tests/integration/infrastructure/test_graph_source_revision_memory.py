import hashlib
import json
import os
import resource
import signal
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from music_analyzer.application.dto.analysis import AnalysisError
from music_analyzer.application.use_cases.build_graph import BuildGraphSnapshot, GRAPH_SOURCE_OVERRIDE_FIELDS
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository
from music_analyzer.infrastructure.persistence.explorer_readonly import ReadOnlyExplorerSQLiteRepository


# 128MiB is intentionally within the issue-44 128-192MiB POSIX RLIMIT_AS
# envelope.  The synthetic source payload is 48MiB (64 rows each below 1MiB):
# large enough for the eager row list + json.dumps copy to raise MemoryError in
# this image, but small enough for the intended streaming digest to fit.
_MEMORY_LIMIT_BYTES = 128 * 1024 * 1024
_STAGE_RESULT_BYTES = 768 * 1024
_TRACK_COUNT = 64
_TIMEOUT_SECONDS = 15
_OVERSIZED_STAGE_BYTES = 17 * 1024 * 1024


def _skip_without_posix_address_space_limit():
    if os.name != 'posix' or not hasattr(resource, 'RLIMIT_AS'):
        raise unittest.SkipTest('POSIX RLIMIT_AS is required for deterministic low-memory source revision coverage')


def _create_large_stage_result_database(path: Path) -> None:
    SQLiteAnalysisRepository(str(path))
    payload = 'x' * _STAGE_RESULT_BYTES
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        for index in range(_TRACK_COUNT):
            track_id = f'track-{index:04d}'
            run_id = f'run-{index:04d}'
            db.execute('INSERT INTO tracks(id,sha256,size) VALUES(?,?,?)', (track_id, f'{index:064x}', index + 1))
            db.execute(
                'INSERT INTO locations(path,track_id,mtime_ns,format,available) VALUES(?,?,?,?,1)',
                (f'/music/{index:04d}.flac', track_id, index + 1, 'flac'),
            )
            db.execute(
                'INSERT INTO track_metadata(track_id,common_json,tags_json,warnings_json) VALUES(?,?,?,?)',
                (track_id, '[]', '[]', '[]'),
            )
            db.execute(
                'INSERT INTO track_audio(track_id,duration_seconds,duration_source,status,reason) VALUES(?,?,?,?,?)',
                (track_id, 120.0, 'mutagen', 'eligible', ''),
            )
            db.execute(
                "INSERT INTO runs(id,location,status,detail) VALUES(?,?, 'completed', '')",
                (run_id, f'/music/{index:04d}.flac'),
            )
            db.execute('INSERT INTO run_tracks(run_id,track_id) VALUES(?,?)', (run_id, track_id))
            db.execute('INSERT INTO stages(run_id,stage,result) VALUES(?,?,?)', (run_id, 'large-stage', payload))


def _create_oversized_stage_database(path: Path) -> None:
    SQLiteAnalysisRepository(str(path))
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('INSERT INTO tracks(id,sha256,size) VALUES(?,?,?)', ('track-oversized', 'a' * 64, 1))
        db.execute(
            'INSERT INTO locations(path,track_id,mtime_ns,format,available) VALUES(?,?,?,?,1)',
            ('/music/oversized.flac', 'track-oversized', 1, 'flac'),
        )
        db.execute(
            'INSERT INTO track_metadata(track_id,common_json,tags_json,warnings_json) VALUES(?,?,?,?)',
            ('track-oversized', '[]', '[]', '[]'),
        )
        db.execute(
            'INSERT INTO track_audio(track_id,duration_seconds,duration_source,status,reason) VALUES(?,?,?,?,?)',
            ('track-oversized', 120.0, 'mutagen', 'eligible', ''),
        )
        db.execute("INSERT INTO runs(id,location,status,detail) VALUES(?,?, 'completed', '')", ('run-oversized', '/music/oversized.flac'))
        db.execute('INSERT INTO run_tracks(run_id,track_id) VALUES(?,?)', ('run-oversized', 'track-oversized'))
        db.execute('INSERT INTO stages(run_id,stage,result) VALUES(?,?,zeroblob(?))', ('run-oversized', 'energy', _OVERSIZED_STAGE_BYTES))


def _create_canonical_source_revision_database(path: Path) -> None:
    SQLiteAnalysisRepository(str(path))
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        fixtures = (
            ('track-a', 'run-a', '/music/10 intro α.flac', (('decode', 'ok'), ('features', '{"tone":"暖"}'))),
            ('track-b', 'run-b', '/music/sub/20,beta.flac', (('decode', 'ok'), ('features', '[1,2,3]'))),
        )
        for index, (track_id, run_id, path_value, stages) in enumerate(fixtures, start=1):
            db.execute('INSERT INTO tracks(id,sha256,size) VALUES(?,?,?)', (track_id, f'{index:064x}', index))
            db.execute(
                'INSERT INTO locations(path,track_id,mtime_ns,format,available) VALUES(?,?,?,?,1)',
                (path_value, track_id, index, 'flac'),
            )
            db.execute(
                'INSERT INTO track_metadata(track_id,common_json,tags_json,warnings_json) VALUES(?,?,?,?)',
                (track_id, '[]', '[]', '[]'),
            )
            db.execute(
                'INSERT INTO track_audio(track_id,duration_seconds,duration_source,status,reason) VALUES(?,?,?,?,?)',
                (track_id, 120.0, 'mutagen', 'eligible', ''),
            )
            db.execute("INSERT INTO runs(id,location,status,detail) VALUES(?,?, 'completed', '')", (run_id, path_value))
            db.execute('INSERT INTO run_tracks(run_id,track_id) VALUES(?,?)', (run_id, track_id))
            db.executemany('INSERT INTO stages(run_id,stage,result) VALUES(?,?,?)', ((run_id, stage, result) for stage, result in stages))
        db.execute('INSERT INTO locations(path,track_id,mtime_ns,format,available) VALUES(?,?,?,?,1)', ('/music/alt α.flac', 'track-a', 3, 'flac'))
        db.execute('INSERT INTO overrides(track_id,field,value) VALUES(?,?,?)', ('track-a', 'bpm', '121.5'))
        db.execute('INSERT INTO overrides(track_id,field,value) VALUES(?,?,?)', ('track-a', 'title', 'irrelevant title'))


def _eager_source_revision(path: Path) -> str:
    rows = []
    with sqlite3.connect(path) as db:
        for track_id, run_id in db.execute('''
                SELECT track_id,run_id FROM (
                    SELECT rt.track_id, r.id AS run_id, r.status AS status,
                           row_number() OVER (PARTITION BY rt.track_id ORDER BY r.rowid DESC) AS rn
                    FROM run_tracks rt JOIN runs r ON r.id=rt.run_id
                    JOIN active_tracks at ON at.id=rt.track_id
                    WHERE EXISTS (SELECT 1 FROM active_locations al WHERE al.track_id=rt.track_id)
                ) WHERE rn=1 AND status='completed' ORDER BY track_id'''):
            stages = tuple(db.execute('SELECT stage,result FROM stages WHERE run_id=? ORDER BY stage', (run_id,)))
            overrides = tuple(db.execute(
                'SELECT field,value FROM overrides WHERE track_id=? AND field IN (?,?,?,?,?) ORDER BY field',
                (track_id, *sorted(GRAPH_SOURCE_OVERRIDE_FIELDS)),
            ))
            active_locations = tuple(db.execute('SELECT path FROM active_locations WHERE track_id=? ORDER BY path', (track_id,)))
            rows.append((track_id, run_id, active_locations, stages, overrides))
    payload = json.dumps(rows, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def _run_python(script: str, db_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, '-c', script, str(db_path), str(_MEMORY_LIMIT_BYTES)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=_TIMEOUT_SECONDS,
    )


_BASELINE_EAGER_SCRIPT = r'''
import hashlib
import json
import resource
import sqlite3
import sys

path = sys.argv[1]
limit = int(sys.argv[2])
resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
source = ''' + repr("""
rows = []
for track_id, run_id in db.execute('''
        SELECT track_id,run_id FROM (
            SELECT rt.track_id, r.id AS run_id, r.status AS status,
                   row_number() OVER (PARTITION BY rt.track_id ORDER BY r.rowid DESC) AS rn
            FROM run_tracks rt JOIN runs r ON r.id=rt.run_id
            JOIN active_tracks at ON at.id=rt.track_id
            WHERE EXISTS (SELECT 1 FROM active_locations al WHERE al.track_id=rt.track_id)
        ) WHERE rn=1 AND status='completed' ORDER BY track_id'''):
    stages = tuple(db.execute('SELECT stage,result FROM stages WHERE run_id=? ORDER BY stage', (run_id,)))
    overrides = tuple(db.execute(
        'SELECT field,value FROM overrides WHERE track_id=? AND field IN (?,?,?,?,?) ORDER BY field',
        (track_id, 'album', 'albumartist', 'artist', 'date', 'title'),
    ))
    active_locations = tuple(db.execute('SELECT path FROM active_locations WHERE track_id=? ORDER BY path', (track_id,)))
    rows.append((track_id, run_id, active_locations, stages, overrides))
payload = json.dumps(rows, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
digest = hashlib.sha256(payload.encode('utf-8')).hexdigest()
print(digest)
""") + r'''
compile(source, '<eager-source-revision-baseline>', 'exec')
try:
    with sqlite3.connect(path) as db:
        exec(source, {'db': db, 'hashlib': hashlib, 'json': json})
except MemoryError:
    print('MemoryError', file=sys.stderr)
    raise SystemExit(73)
'''


_REPOSITORY_SOURCE_REVISION_SCRIPT = r'''
import resource
import sys
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository

path = sys.argv[1]
limit = int(sys.argv[2])
resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
digest = SQLiteAnalysisRepository(path).source_revision()
if len(digest) != 64 or any(ch not in '0123456789abcdef' for ch in digest):
    raise SystemExit(f'unexpected digest: {digest!r}')
print(digest)
'''


_OVERSIZED_SOURCE_REVISION_SCRIPT = r'''
import resource
import sys
from music_analyzer.application.dto.analysis import AnalysisError
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository

path = sys.argv[1]
limit = int(sys.argv[2])
resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
try:
    SQLiteAnalysisRepository(path).source_revision()
except AnalysisError as error:
    print(str(error))
    raise SystemExit(42)
except MemoryError:
    print('MemoryError', file=sys.stderr)
    raise SystemExit(73)
raise SystemExit('expected AnalysisError')
'''


class GraphSourceRevisionMemoryTests(unittest.TestCase):
    def test_source_revision_matches_eager_canonical_digest_and_tracks_relevant_inputs(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / 'analysis.sqlite'
            _create_canonical_source_revision_database(db_path)
            repo = SQLiteAnalysisRepository(str(db_path))

            original = repo.source_revision()
            self.assertEqual(original, _eager_source_revision(db_path))
            self.assertEqual(repo.source_revision(), original)

            with sqlite3.connect(db_path) as db:
                db.execute(
                    "UPDATE overrides SET value='renamed but graph-irrelevant' "
                    "WHERE track_id='track-a' AND field='title'"
                )
            self.assertEqual(repo.source_revision(), original)

            with sqlite3.connect(db_path) as db:
                db.execute(
                    "UPDATE locations SET path='/music/moved α.flac' "
                    "WHERE track_id='track-a' AND path='/music/10 intro α.flac'"
                )
            moved = repo.source_revision()
            self.assertNotEqual(moved, original)
            self.assertEqual(moved, _eager_source_revision(db_path))

            repo.set_override('track-a', 'bpm', '122.0')
            overridden = repo.source_revision()
            self.assertNotEqual(overridden, moved)
            self.assertEqual(overridden, _eager_source_revision(db_path))

    def test_oversized_stored_stage_fails_before_fetching_raw_source_revision_under_low_address_space(self):
        _skip_without_posix_address_space_limit()
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / 'analysis.sqlite'
            _create_oversized_stage_database(db_path)

            checked = _run_python(_OVERSIZED_SOURCE_REVISION_SCRIPT, db_path)

        self.assertEqual(
            checked.returncode,
            42,
            f'oversized stage should fail with AnalysisError, not MemoryError; '
            f'stdout={checked.stdout!r} stderr={checked.stderr!r}',
        )
        self.assertIn('Oversized stored stage (16 MiB limit)', checked.stdout)
        self.assertNotIn('MemoryError', checked.stderr)

    def test_graph_build_reports_oversized_stored_stage_before_reading_live_data(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / 'analysis.sqlite'
            _create_oversized_stage_database(db_path)
            writer = SQLiteAnalysisRepository(str(db_path))
            reader = ReadOnlyExplorerSQLiteRepository(str(db_path))

            with self.assertRaisesRegex(AnalysisError, r'Oversized stored stage \(16 MiB limit\)'):
                BuildGraphSnapshot(reader, writer).execute()

    def test_source_revision_streams_large_stage_results_under_low_address_space(self):
        _skip_without_posix_address_space_limit()
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / 'analysis.sqlite'
            _create_large_stage_result_database(db_path)

            baseline = _run_python(_BASELINE_EAGER_SCRIPT, db_path)
            self.assertEqual(
                baseline.returncode,
                73,
                f'eager baseline should compile then fail specifically with MemoryError under '
                f'{_MEMORY_LIMIT_BYTES // (1024 * 1024)}MiB RLIMIT_AS; '
                f'stdout={baseline.stdout!r} stderr={baseline.stderr!r}',
            )
            self.assertIn('MemoryError', baseline.stderr)

            streamed = _run_python(_REPOSITORY_SOURCE_REVISION_SCRIPT, db_path)

        self.assertEqual(
            streamed.returncode,
            0,
            f'source_revision should stream canonical digest under '
            f'{_MEMORY_LIMIT_BYTES // (1024 * 1024)}MiB RLIMIT_AS; '
            f'stdout={streamed.stdout!r} stderr={streamed.stderr!r}',
        )
        digest = streamed.stdout.strip()
        self.assertEqual(len(digest), 64)
        self.assertTrue(all(ch in '0123456789abcdef' for ch in digest))


if __name__ == '__main__':
    unittest.main()
