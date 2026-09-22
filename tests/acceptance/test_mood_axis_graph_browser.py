import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import urlopen

from tests.acceptance.test_explorer_3d_graph_assets import create_three_track_graph_db
from music_analyzer.frameworks.explorer.server import create_server


class MoodAxisGraphBrowserSmoke(unittest.TestCase):
    def test_server_serves_offline_bundle_and_mood_axis_api(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / 'analysis.sqlite'
            ids = create_three_track_graph_db(db)
            server = create_server(str(db), port=0)
            try:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base = f'http://127.0.0.1:{server.server_port}'
                with urlopen(base + '/vendor/3d-force-graph/3d-force-graph.min.js', timeout=5) as response:
                    bundle = response.read(128).decode('utf-8')
                self.assertIn('3d-force-graph', bundle)
                with urlopen(base + '/api/mood-axis-graph?mood=happy', timeout=5) as response:
                    graph = json.loads(response.read().decode('utf-8'))
                self.assertEqual(graph['selected_mood'], 'happy')
                self.assertEqual({node['track_id'] for node in graph['positioned']}, set(ids[:2]))
                self.assertEqual(len(graph['unpositioned']), 1)
                self.assertTrue(all(node['x']['label'] == 'valence' for node in graph['positioned']))
                self.assertTrue(all(node['y']['label'] == 'arousal' for node in graph['positioned']))
                self.assertTrue(all(node['z']['label'] == 'happy' for node in graph['positioned']))
            finally:
                server.shutdown(); server.server_close()


if __name__ == '__main__':
    unittest.main()
