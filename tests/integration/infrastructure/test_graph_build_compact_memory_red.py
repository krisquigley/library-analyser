import json
import os
import resource
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository


_MEMORY_LIMIT_BYTES = 192 * 1024 * 1024
_TARGET_STAGE_BYTES = 768 * 1024
_TRACK_COUNT = 64
_TIMEOUT_SECONDS = 20
_RUN_ENV = 'LIBRARY_ANALYSER_RUN_ISSUE44_GRAPH_BUILD_MEMORY_RED'


def _skip_unless_opted_in_low_memory_graph_build():
    if os.environ.get(_RUN_ENV) != '1':
        raise unittest.SkipTest(f'set {_RUN_ENV}=1 to run the issue-44 low-memory graph-build red test')
    if os.name != 'posix' or not hasattr(resource, 'RLIMIT_AS'):
        raise unittest.SkipTest('POSIX RLIMIT_AS is required for deterministic low-memory graph-build coverage')


def _stage_payload(stage, *, values=(), summary=None, windows=()):
    data = {
        'stage': stage,
        'provenance': [['model', _model_for(stage)], ['fixture', 'issue44-compact-build-red']],
        'uncertainty': '',
        'values': [list(item) for item in values],
    }
    if summary is not None:
        labels, mean = summary
        data['summary'] = {
            'labels': list(labels),
            'mean': list(mean),
            'minimum': list(mean),
            'maximum': list(mean),
            'coverage': 1.0,
            'provisional': False,
            'uncertainty': '',
        }
    if windows:
        data['windows'] = list(windows)
    return json.dumps(data, sort_keys=True, separators=(',', ':'))


def _model_for(stage):
    return {
        'energy': 'emomusic-msd-musicnn-2',
        'mood': 'mtg_jamendo_moodtheme-discogs-effnet-1',
        'genres': 'genre_discogs400-discogs-effnet-1',
    }.get(stage, 'fixture-' + stage)


def _large_energy_payload(valence, arousal):
    windows = []
    payload = ''
    index = 0
    # Keep each stage row comfortably below SQLite/read-side 1MiB while making
    # the complete fixture large enough (64 * ~768KiB) to expose eager graph
    # candidate retention after streamed source_revision succeeds.
    while len(payload.encode('utf-8')) < _TARGET_STAGE_BYTES:
        windows.append({'start': index, 'end': index + 1, 'scores': [valence, arousal]})
        index += 1
        if index % 256 == 0:
            payload = _stage_payload('energy', summary=(('valence', 'arousal'), (valence, arousal)), windows=windows)
    payload = _stage_payload('energy', summary=(('valence', 'arousal'), (valence, arousal)), windows=windows)
    if len(payload.encode('utf-8')) > 1024 * 1024:
        raise AssertionError('synthetic energy stage exceeded the <=1MiB row contract')
    return payload


def _create_compact_valid_large_graph_database(path: Path) -> None:
    SQLiteAnalysisRepository(str(path))
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if version != 10:
            raise AssertionError(f'expected schema v10, got {version}')
        for index in range(_TRACK_COUNT):
            suffix = f'{index:064x}'
            track_id = 'sha256:' + suffix
            run_id = f'run-{index:04d}'
            path_value = f'/music/{index:04d}.flac'
            bpm = 90.0 + (index % 80)
            valence = round((index % 17) / 16, 6)
            arousal = round((index % 19) / 18, 6)
            mood_relaxing = round((index % 23) / 22, 6)
            genre_rock = round((index % 29) / 28, 6)
            db.execute('INSERT INTO tracks(id,sha256,size) VALUES(?,?,?)', (track_id, suffix, index + 1))
            db.execute('INSERT INTO locations(path,track_id,mtime_ns,format,available) VALUES(?,?,?,?,1)', (path_value, track_id, index + 1, 'flac'))
            db.execute('INSERT INTO scan_roots(root,path) VALUES(?,?)', ('/music', path_value))
            db.execute('INSERT INTO track_metadata(track_id,common_json,tags_json,warnings_json) VALUES(?,?,?,?)', (track_id, '[]', '[]', '[]'))
            db.execute('INSERT INTO track_audio(track_id,duration_seconds,duration_source,status,reason) VALUES(?,?,?,?,?)', (track_id, 180.0, 'mutagen', 'eligible', ''))
            db.execute("INSERT INTO runs(id,location,status,detail) VALUES(?,?, 'completed', '')", (run_id, path_value))
            db.execute('INSERT INTO run_tracks(run_id,track_id) VALUES(?,?)', (run_id, track_id))
            db.execute('INSERT INTO stages(run_id,stage,result) VALUES(?,?,?)', (run_id, 'bpm', _stage_payload('bpm', values=(('bpm', bpm),))))
            db.execute('INSERT INTO stages(run_id,stage,result) VALUES(?,?,?)', (run_id, 'energy', _large_energy_payload(valence, arousal)))
            db.execute('INSERT INTO stages(run_id,stage,result) VALUES(?,?,?)', (run_id, 'mood', _stage_payload('mood', summary=(('relaxing', 'heavy'), (mood_relaxing, 1.0 - mood_relaxing)))))
            db.execute('INSERT INTO stages(run_id,stage,result) VALUES(?,?,?)', (run_id, 'genres', _stage_payload('genres', summary=(('rock', 'jazz'), (genre_rock, 1.0 - genre_rock)))))


def _run_capped_graph_build(db_path: Path) -> subprocess.CompletedProcess:
    script = r'''
import resource
import sys
from music_analyzer.application.use_cases.build_graph import BuildGraphSnapshot
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository
from music_analyzer.infrastructure.persistence.explorer_readonly import ReadOnlyExplorerSQLiteRepository

path = sys.argv[1]
limit = int(sys.argv[2])
resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
writer = SQLiteAnalysisRepository(path)
reader = ReadOnlyExplorerSQLiteRepository(path)
revision = writer.source_revision()
print('source_revision_ok=' + revision, flush=True)
try:
    result = BuildGraphSnapshot(reader, writer).execute()
except MemoryError:
    print('MemoryError during graph BuildGraphSnapshot.execute after streamed source_revision; eager candidate_snapshot retention is still present', file=sys.stderr)
    raise SystemExit(73)
print(f'Built {result.edge_count} graph edges', flush=True)
'''
    return subprocess.run(
        [sys.executable, '-c', script, str(db_path), str(_MEMORY_LIMIT_BYTES)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=_TIMEOUT_SECONDS,
    )


class GraphBuildCompactMemoryRedTests(unittest.TestCase):
    def test_graph_build_uses_compact_streaming_source_under_low_address_space(self):
        _skip_unless_opted_in_low_memory_graph_build()
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / 'analysis.sqlite'
            _create_compact_valid_large_graph_database(db_path)
            result = _run_capped_graph_build(db_path)

        self.assertEqual(
            result.returncode,
            0,
            f'graph build should stream compact graph source tracks under '
            f'{_MEMORY_LIMIT_BYTES // (1024 * 1024)}MiB RLIMIT_AS after source_revision; '
            f'baseline is expected to fail here by eager candidate_snapshot retention, not by malformed fixture. '
            f'stdout={result.stdout!r} stderr={result.stderr!r}',
        )
        self.assertIn('Built ', result.stdout)


if __name__ == '__main__':
    unittest.main()
