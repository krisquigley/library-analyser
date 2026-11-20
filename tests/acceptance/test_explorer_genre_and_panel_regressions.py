"""Explorer filter and panel behavior across both delivery packages."""
import json
import sqlite3
import tempfile
import threading
from urllib.request import urlopen
import unittest
from pathlib import Path
from urllib.parse import urlencode
from tests.support.three_track_graph_db import create_three_track_graph_db
from music_analyzer.frameworks.explorer.server import create_server as analyzer_server
from music_explorer.frameworks.explorer.server import create_server as standalone_server

from music_analyzer.application.use_cases.explorer import BuildMoodAxisGraph as AnalyzerGraph, FilterMoodAxisGraph as AnalyzerFilter
from music_explorer.application.use_cases.explorer import BuildMoodAxisGraph as StandaloneGraph, FilterMoodAxisGraph as StandaloneFilter
from tests.unit.application.test_mood_axis_graph import FakeRepo, track

ROOT = Path(__file__).resolve().parents[2]
LABEL = 'Folk, World, & Country---Folk'


class ExplorerGenreAndPanelRegressions(unittest.TestCase):
    def test_filter_matches_retained_genre_even_below_provisional_cutoff(self):
        for graph_use_case, filter_use_case in ((AnalyzerGraph, AnalyzerFilter), (StandaloneGraph, StandaloneFilter)):
            with self.subTest(graph=graph_use_case):
                graph = graph_use_case(FakeRepo([track('a', genres=((LABEL, 'Other'), (0.2, 0.05)))])).execute()
                self.assertEqual([n.track_id for n in filter_use_case().execute(graph, genres=(LABEL,)).positioned], ['sha256:' + 'a' * 64])

    def test_api_preserves_comma_ampersand_in_discogs_label(self):
        for create_server in (analyzer_server, standalone_server):
            with self.subTest(server=create_server), tempfile.TemporaryDirectory() as td:
                db_path = Path(td) / 'library.sqlite'
                ids = create_three_track_graph_db(db_path)
                con = sqlite3.connect(db_path)
                payload = json.loads(con.execute("SELECT result FROM stages WHERE run_id='run-1' AND stage='genres'").fetchone()[0])
                payload['summary']['labels'][0] = LABEL
                payload['summary']['mean'][0] = 0.2
                con.execute("UPDATE stages SET result=? WHERE run_id='run-1' AND stage='genres'", (json.dumps(payload),))
                con.commit(); con.close()
                server = create_server(str(db_path), port=0)
                try:
                    thread = threading.Thread(target=server.serve_forever, daemon=True)
                    thread.start()
                    query = urlencode({'genre': LABEL})
                    with urlopen(f'http://127.0.0.1:{server.server_port}/api/mood-axis-graph?{query}', timeout=5) as response:
                        graph = json.load(response)
                    self.assertIn(ids[0], [node['track_id'] for node in graph['positioned']])
                finally:
                    server.shutdown(); server.server_close()
