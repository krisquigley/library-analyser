from contextlib import closing
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from music_explorer.frameworks.explorer.server import create_server
from tests.acceptance.test_explorer_3d_graph_assets import create_three_track_graph_db


class CompactMoodAxisGraphHttpContractRedTests(unittest.TestCase):
    def _with_server(self):
        td = tempfile.TemporaryDirectory()
        db = Path(td.name) / 'analysis.sqlite'
        ids = create_three_track_graph_db(db)
        server = create_server(str(db), port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return td, server, ids

    def test_default_mood_axis_graph_remains_legacy_verbose_shape_baseline_guard(self):
        td, server, ids = self._with_server()
        try:
            base = f'http://127.0.0.1:{server.server_port}'
            with urlopen(base + '/api/mood-axis-graph?mood=relaxing', timeout=5) as response:
                graph = json.loads(response.read().decode('utf-8'))
            self.assertIn('positioned', graph)
            self.assertIn('edges', graph)
            self.assertNotIn('dto_version', graph)
            self.assertEqual({node['track_id'] for node in graph['positioned']}, set(ids[:2]))
        finally:
            server.shutdown(); server.server_close(); td.cleanup()

    def test_contract_v2_returns_versioned_compact_graph_without_verbose_top_level_arrays(self):
        td, server, ids = self._with_server()
        try:
            base = f'http://127.0.0.1:{server.server_port}'
            with urlopen(base + '/api/mood-axis-graph?contract=v2&mood=relaxing', timeout=5) as response:
                compact = json.loads(response.read().decode('utf-8'))
            self.assertIn('dto_version', compact, 'contract=v2 must opt in to the compact versioned DTO, not legacy JSON')
            self.assertEqual(compact['dto_version'], 'mood-axis-graph-compact-v1')
            self.assertEqual(compact['selected_mood'], 'relaxing')
            self.assertIn('metadata', compact)
            self.assertEqual({node['id'] for node in compact['nodes']}, set(ids[:2]))
            self.assertEqual(len(compact['unpositioned']), 1)
            self.assertIn('links', compact)
            self.assertNotIn('positioned', compact)
            self.assertNotIn('edges', compact)
            node = next(node for node in compact['nodes'] if node['id'] == ids[0])
            self.assertEqual(node['label'], 'Alpha.flac')
            self.assertEqual(node['axis']['x']['label'], 'valence')
            self.assertEqual(node['axis']['x']['raw'], 0.7)
            self.assertEqual(node['axis']['x']['normalized'], 0.7)
            self.assertEqual(node['axis']['z']['raw'], 120.0)
            self.assertEqual(node['bpm'], 120.0)
            self.assertEqual(node['genres'], [['jazz', 0.2], ['rock', 0.8]])
            self.assertEqual(node['genre_threshold'], 0.5)
            self.assertEqual(node['mood_score']['label'], 'relaxing')
            self.assertEqual(node['mood_score']['raw'], 0.9)
            self.assertIsInstance(compact['links'], list)
            json.dumps(compact, sort_keys=True, ensure_ascii=False, allow_nan=False)
        finally:
            server.shutdown(); server.server_close(); td.cleanup()

    def test_unknown_mood_axis_graph_contract_is_rejected_clearly(self):
        td, server, _ids = self._with_server()
        try:
            base = f'http://127.0.0.1:{server.server_port}'
            with self.assertRaises(HTTPError) as raised:
                urlopen(base + '/api/mood-axis-graph?contract=v99', timeout=5)
            self.assertEqual(raised.exception.code, 400)
            body = raised.exception.read().decode('utf-8')
            self.assertIn('contract', body.lower())
        finally:
            server.shutdown(); server.server_close(); td.cleanup()

    def test_blank_mood_axis_graph_contract_is_rejected_clearly(self):
        td, server, _ids = self._with_server()
        try:
            base = f'http://127.0.0.1:{server.server_port}'
            with self.assertRaises(HTTPError) as raised:
                urlopen(base + '/api/mood-axis-graph?contract=', timeout=5)
            with closing(raised.exception) as error:
                self.assertEqual(error.code, 400)
                body = error.read().decode('utf-8')
            self.assertIn('contract', body.lower())
        finally:
            server.shutdown(); server.server_close(); td.cleanup()

    def test_duplicate_same_mood_axis_graph_contract_is_rejected_clearly(self):
        td, server, _ids = self._with_server()
        try:
            base = f'http://127.0.0.1:{server.server_port}'
            with self.assertRaises(HTTPError) as raised:
                urlopen(base + '/api/mood-axis-graph?contract=v2&contract=v2', timeout=5)
            with closing(raised.exception) as error:
                self.assertEqual(error.code, 400)
                body = error.read().decode('utf-8')
            self.assertIn('contract', body.lower())
        finally:
            server.shutdown(); server.server_close(); td.cleanup()

    def test_duplicate_conflicting_mood_axis_graph_contract_is_rejected_clearly(self):
        td, server, _ids = self._with_server()
        try:
            base = f'http://127.0.0.1:{server.server_port}'
            with self.assertRaises(HTTPError) as raised:
                urlopen(base + '/api/mood-axis-graph?contract=v2&contract=legacy', timeout=5)
            with closing(raised.exception) as error:
                self.assertEqual(error.code, 400)
                body = error.read().decode('utf-8')
            self.assertIn('contract', body.lower())
        finally:
            server.shutdown(); server.server_close(); td.cleanup()

    def test_compact_payload_is_substantially_smaller_than_legacy_on_synthetic_fixture(self):
        td, server, _ids = self._with_server()
        try:
            base = f'http://127.0.0.1:{server.server_port}'
            with urlopen(base + '/api/mood-axis-graph?mood=relaxing', timeout=5) as response:
                legacy_bytes = response.read()
            with urlopen(base + '/api/mood-axis-graph?contract=v2&mood=relaxing', timeout=5) as response:
                compact_bytes = response.read()
            self.assertLess(len(compact_bytes), len(legacy_bytes) * 0.8)
        finally:
            server.shutdown(); server.server_close(); td.cleanup()


if __name__ == '__main__':
    unittest.main()
