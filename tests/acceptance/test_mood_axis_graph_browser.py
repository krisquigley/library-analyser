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
                with urlopen(base + '/api/mood-axis-graph?mood=relaxing', timeout=5) as response:
                    graph = json.loads(response.read().decode('utf-8'))
                self.assertEqual(graph['selected_mood'], 'relaxing')
                self.assertEqual({node['track_id'] for node in graph['positioned']}, set(ids[:2]))
                self.assertEqual(len(graph['unpositioned']), 1)
                self.assertTrue(all(node['x']['label'] == 'valence' for node in graph['positioned']))
                self.assertTrue(all(node['y']['label'] == 'arousal' for node in graph['positioned']))
                self.assertTrue(all(node['z']['label'] == 'BPM' and node['mood_score']['label'] == 'relaxing' for node in graph['positioned']))
                with urlopen(base + '/api/mood-axis-graph?mood=relaxing&bpm_min=119&bpm_max=121&genre=jazz', timeout=5) as response:
                    filtered = json.loads(response.read().decode('utf-8'))
                self.assertEqual(filtered['positioned'], [])
            finally:
                server.shutdown(); server.server_close()

    def test_mood_axis_api_does_not_abort_when_database_has_no_supported_mood_labels(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / 'analysis.sqlite'
            ids = create_three_track_graph_db(db)
            first = ids[0]
            server = create_server(str(db), port=0)
            try:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base = f'http://127.0.0.1:{server.server_port}'
                from urllib.error import HTTPError
                try:
                    urlopen(base + '/api/mood-axis-graph?mood=unsupported', timeout=5)
                    self.fail('unsupported mood request should be rejected')
                except HTTPError as error:
                    self.assertEqual(error.code, 400)
                # Remove mood stages to exercise the graceful no-supported-mood default view.
                import sqlite3
                con = sqlite3.connect(db)
                con.execute("DELETE FROM stages WHERE stage='mood'")
                con.commit(); con.close()
                with urlopen(base + '/api/mood-axis-graph', timeout=5) as response:
                    graph = json.loads(response.read().decode('utf-8'))
                self.assertEqual(graph['selected_mood'], '')
                self.assertEqual(graph['available_moods'], [])
                self.assertEqual({item['track_id'] for item in graph['positioned']}, set(ids[:2]))
                self.assertTrue(all(item['mood_score'] is None for item in graph['positioned']))
                self.assertEqual({item['track_id'] for item in graph['unpositioned']}, {ids[2]})
                with urlopen(base + '/api/tracks/' + first, timeout=5) as response:
                    detail = json.loads(response.read().decode('utf-8'))
                self.assertEqual(detail['fields']['bpm']['automatic']['values'], [['bpm', 120.0]])
                self.assertEqual(detail['fields']['energy']['automatic']['summary_values'], [['arousal', 0.2], ['valence', 0.7]])
            finally:
                server.shutdown(); server.server_close()


if __name__ == '__main__':
    unittest.main()
