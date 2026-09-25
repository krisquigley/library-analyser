"""Explorer filter and panel behavior across both delivery packages."""
import json
import sqlite3
import tempfile
import threading
from urllib.request import urlopen
import shutil
import subprocess
import unittest
from pathlib import Path
from urllib.parse import urlencode
from tests.acceptance.test_explorer_3d_graph_assets import create_three_track_graph_db
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

    @unittest.skipUnless(shutil.which('node'), 'Node required for browser behavior test')
    def test_browser_options_filter_and_panels_in_both_packages(self):
        script = r'''
const assert = require('assert');
const fs = require('fs');
const app = require(process.argv[1]);
const html = fs.readFileSync(process.argv[2], 'utf8');
const label = 'Folk, World, & Country---Folk';
const node = {track_id:'a',display_label:'A',x:{raw:0.1,normalized:0.1},y:{raw:0.2,normalized:0.2},z:{raw:120,normalized:6},bpm:120,genres:[[label,0.2],['Other',0.05]],genre_threshold:0.5};
const model = app.buildMoodGraphModel({positioned:[node],edges:[]});
assert(model.genreOptions.includes(label));
assert(!model.genreOptions.includes('Other'), 'options should only include genres with matching nodes');
assert.deepStrictEqual(app.applyMoodGraphFilters(model,{genres:[label]}).nodes.map(n=>n.id),['a']);
assert(!html.includes('id="candidates"'), 'remove numbered list below candidate controls');
assert(html.includes('id="controls"') && html.includes('id="tracks-panel"'));
const element = tag => ({tagName:tag,children:[],textContent:'',className:'',append(...items){this.children.push(...items)},replaceChildren(...items){this.children=items}});
const detail = element('div');
global.document = {getElementById:id=>id==='detail'?detail:null,createElement:element};
app.renderDetail({reasons:['genres: provisional, uncalibrated scores','energy: uncertainty'],metadata:{common:[['title','A']],tags:[]},fields:{}});
assert(!JSON.stringify(detail).includes('provisional, uncalibrated'));
assert(!JSON.stringify(detail).includes('energy: uncertainty'));
assert(JSON.stringify(detail).includes('Title: A'));
'''
        for package in ('music_analyzer', 'music_explorer'):
            with self.subTest(package=package):
                assets = ROOT / package / 'frameworks/explorer/assets'
                subprocess.run(['node', '-e', script, str(assets / 'app.js'), str(assets / 'index.html')], check=True)
