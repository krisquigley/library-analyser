import contextlib
from contextlib import closing
import io
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

from music_analyzer.frameworks.cli.main import main
from music_analyzer.frameworks.explorer.server import create_server
from tests.acceptance.test_explorer_3d_graph_assets import create_three_track_graph_db


def _run_cli(argv):
    with contextlib.redirect_stdout(io.StringIO()) as stdout, contextlib.redirect_stderr(io.StringIO()) as stderr:
        try:
            code = main(argv)
        except SystemExit as error:
            code = error.code
    return code, stdout.getvalue(), stderr.getvalue()


def _build_warm_graph_database(path: Path):
    ids = create_three_track_graph_db(path)
    code, stdout, stderr = _run_cli(['graph', 'build', '--database', str(path)])
    if code != 0:
        raise AssertionError(f'graph build failed with {code}: stdout={stdout!r} stderr={stderr!r}')
    return ids


def _current_persisted_edges(path: Path):
    with closing(sqlite3.connect(path)) as db:
        return tuple(db.execute('''
            SELECT e.source_track_id,e.target_track_id,e.score,e.supported_group_count
            FROM graph_builds b
            JOIN graph_build_edges e ON e.build_id=b.id
            WHERE b.is_current=1 AND b.status='completed'
            ORDER BY e.source_track_id,e.target_track_id
        '''))


def _fetch_json(url: str):
    try:
        with urlopen(url, timeout=5) as response:
            return response.status, json.loads(response.read().decode('utf-8'))
    except HTTPError as error:
        return error.code, json.loads(error.read().decode('utf-8'))


class MoodAxisGraphWarmCacheRedTests(unittest.TestCase):
    def test_v7_mood_axis_graph_reads_warm_persisted_edges_without_recomputing_bounded_edges(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / 'analysis.sqlite'
            _build_warm_graph_database(db_path)
            expected_edges = _current_persisted_edges(db_path)
            self.assertGreater(len(expected_edges), 0, 'fixture graph build should persist at least one warm edge')

            server = create_server(str(db_path), port=0)
            try:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                with patch(
                    'music_explorer.application.use_cases.explorer._bounded_edges',
                    side_effect=AssertionError('warm /api/mood-axis-graph must read persisted graph_build_edges, not recompute _bounded_edges'),
                ):
                    status, graph = _fetch_json(f'http://127.0.0.1:{server.server_port}/api/mood-axis-graph?mood=relaxing')
            finally:
                server.shutdown(); server.server_close()

            self.assertEqual(status, 200, graph)
            self.assertEqual(
                tuple((edge['a'], edge['b'], edge['score'], edge['supported_group_count']) for edge in graph['edges']),
                expected_edges,
            )
            self.assertEqual(graph['metadata']['graph_status']['state'], 'ready')
            self.assertEqual(graph['metadata']['graph_status']['source'], 'graph_build_edges')

    def test_graph_relevant_override_invalidates_warm_snapshot_and_next_read_reports_stale_without_edges(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / 'analysis.sqlite'
            ids = _build_warm_graph_database(db_path)

            code, stdout, stderr = _run_cli(['override', 'set', '--database', str(db_path), ids[0], 'bpm', '121.0'])
            self.assertEqual(code, 0, stdout + stderr)
            with closing(sqlite3.connect(db_path)) as db:
                self.assertEqual(
                    db.execute('SELECT count(*) FROM graph_builds WHERE is_current=1').fetchone()[0],
                    0,
                    'graph-relevant override writes must invalidate the current warm graph snapshot',
                )

            server = create_server(str(db_path), port=0)
            try:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                with patch(
                    'music_explorer.application.use_cases.explorer._bounded_edges',
                    side_effect=AssertionError('stale /api/mood-axis-graph must report graph status, not recompute replacement edges'),
                ):
                    status, payload = _fetch_json(f'http://127.0.0.1:{server.server_port}/api/mood-axis-graph?mood=relaxing')
            finally:
                server.shutdown(); server.server_close()

            self.assertIn(status, {200, 409}, payload)
            self.assertEqual(payload['metadata']['graph_status']['state'], 'stale')
            self.assertIn('music-analyzer graph build --database', payload['metadata']['graph_status']['action'])
            self.assertEqual(payload.get('edges', []), [], 'stale graph responses must not return wrong cached or recomputed edges')


if __name__ == '__main__':
    unittest.main()
