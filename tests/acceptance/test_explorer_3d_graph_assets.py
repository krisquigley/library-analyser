import json
import sqlite3
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.acceptance.test_explorer_server import APP_ID
from music_analyzer.frameworks.explorer.server import create_server


REPO_ROOT = Path(__file__).resolve().parents[2]
APP_JS = REPO_ROOT / 'music_analyzer' / 'frameworks' / 'explorer' / 'assets' / 'app.js'


def create_three_track_graph_db(path):
    db = sqlite3.connect(path)
    db.executescript('''
CREATE TABLE runs (id TEXT PRIMARY KEY, location TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('running','completed','failed','interrupted')), detail TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE stages (run_id TEXT NOT NULL REFERENCES runs(id), stage TEXT NOT NULL, result TEXT NOT NULL, PRIMARY KEY(run_id,stage));
CREATE TABLE tracks(id TEXT PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, size INTEGER NOT NULL);
CREATE TABLE locations(path TEXT PRIMARY KEY, track_id TEXT NOT NULL REFERENCES tracks(id), mtime_ns INTEGER NOT NULL, format TEXT NOT NULL, available INTEGER NOT NULL CHECK(available IN (0,1)));
CREATE TABLE scan_roots(root TEXT NOT NULL, path TEXT NOT NULL REFERENCES locations(path), PRIMARY KEY(root,path));
CREATE TABLE batch_jobs(track_id TEXT PRIMARY KEY REFERENCES tracks(id), fingerprint TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('pending','running','completed','failed')), attempts INTEGER NOT NULL CHECK(attempts >= 0), run_id TEXT, detail TEXT NOT NULL);
CREATE TABLE run_tracks(run_id TEXT PRIMARY KEY REFERENCES runs(id), track_id TEXT NOT NULL REFERENCES tracks(id));
CREATE TABLE overrides(track_id TEXT NOT NULL REFERENCES tracks(id), field TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY(track_id,field));
''')
    db.execute(f'PRAGMA application_id={APP_ID}')
    db.execute('PRAGMA user_version=4')
    ids = []
    rows = (
        ('1', 'Alpha.flac', 120.0, 'C major', 0.2, 0.7, (0.8, 0.2), (0.9, 0.1)),
        ('2', 'Beta.flac', 128.0, 'G major', 0.5, 0.3, (0.4, 0.6), (0.2, 0.8)),
        ('3', 'Isolated Missing.flac', None, None, None, None, None, None),
    )
    for suffix, label, bpm, key, arousal, valence, genre, mood in rows:
        tid = 'sha256:' + suffix * 64
        ids.append(tid)
        db.execute('INSERT INTO tracks VALUES(?,?,?)', (tid, tid.split(':')[1], 10))
        available = 0 if suffix == '3' else 1
        db.execute('INSERT INTO locations VALUES(?,?,?,?,?)', ('/music/' + label, tid, 1, 'flac', available))
        if bpm is not None:
            run_id = 'run-' + suffix
            db.execute('INSERT INTO runs(id,location,status,detail) VALUES(?,?,?,?)', (run_id, '/music/' + label, 'completed', ''))
            db.execute('INSERT INTO run_tracks VALUES(?,?)', (run_id, tid))
            def summary(labels, values):
                return {'labels': list(labels), 'mean': list(values), 'minimum': list(values), 'maximum': list(values), 'coverage': 1.0, 'provisional': True, 'uncertainty': ''}
            stages = [
                ('bpm', {'stage': 'bpm', 'provenance': [], 'uncertainty': '', 'values': [['bpm', bpm]]}),
                ('key', {'stage': 'key', 'provenance': [], 'uncertainty': '', 'values': [['key', key]]}),
                ('energy', {'stage': 'energy', 'provenance': [], 'uncertainty': '', 'values': [], 'summary': summary(('arousal', 'valence'), (arousal, valence))}),
                ('genres', {'stage': 'genres', 'provenance': [['model', 'test']], 'uncertainty': '', 'values': [], 'summary': summary(('rock', 'jazz'), genre)}),
                ('mood', {'stage': 'mood', 'provenance': [['model', 'test']], 'uncertainty': '', 'values': [], 'summary': summary(('happy', 'sad'), mood)}),
            ]
            for stage, payload in stages:
                db.execute('INSERT INTO stages VALUES(?,?,?)', (run_id, stage, json.dumps(payload)))
    db.commit(); db.close()
    return ids


class Explorer3DGraphAssetTests(unittest.TestCase):
    def test_projection_endpoint_exposes_all_library_tracks_for_unbounded_initial_graph(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / 'analysis.sqlite'
            ids = create_three_track_graph_db(db)
            server = create_server(str(db), port=0)
            try:
                # Exercise the API through the handler helper without depending on a browser.
                import threading
                from urllib.request import urlopen
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                with urlopen(f'http://127.0.0.1:{server.server_port}/api/state', timeout=5) as response:
                    state = json.loads(response.read().decode('utf-8'))
                self.assertIsNone(state['current_track_id'])
                with urlopen(f'http://127.0.0.1:{server.server_port}/api/tracks?limit=all', timeout=5) as response:
                    listing = json.loads(response.read().decode('utf-8'))
                self.assertEqual({track['handle'] for track in listing['tracks']}, set(ids))
                with urlopen(f'http://127.0.0.1:{server.server_port}/api/projection', timeout=5) as response:
                    projection = json.loads(response.read().decode('utf-8'))
                self.assertEqual({track['track_id'] for track in projection['tracks']}, set(ids))
                self.assertIn('z', projection['tracks'][0])
                self.assertIn('3d_coordinate_policy', projection['policy_versions'])
            finally:
                server.shutdown(); server.server_close()

    def test_vanilla_js_graph_model_has_stable_3d_positions_filtering_and_clear(self):
        script = r"""
const assert = require('assert');
const graph = require(process.argv[1]);
const tracks = [
  {handle:'a', track_id:'a', display_label:'Alpha', latest_run_status:'completed', available_locations:1, fields:{bpm:{effective_source:'automatic'}, key:{effective_source:'automatic'}, genres:{effective_source:'automatic'}, mood:{effective_source:'automatic'}, energy:{effective_source:'automatic'}}, reasons:[]},
  {handle:'b', track_id:'b', display_label:'Beta', latest_run_status:'completed', available_locations:1, fields:{bpm:{effective_source:'automatic'}, key:{effective_source:'missing'}, genres:{effective_source:'automatic'}, mood:{effective_source:'missing'}, energy:{effective_source:'automatic'}}, reasons:['key: missing result','mood: missing result']},
  {handle:'c', track_id:'c', display_label:'Missing', latest_run_status:null, available_locations:0, fields:{bpm:{effective_source:'missing'}, key:{effective_source:'missing'}, genres:{effective_source:'missing'}, mood:{effective_source:'missing'}, energy:{effective_source:'missing'}}, reasons:['No available catalogue location']}
];
const projection = {tracks:[
  {track_id:'a',x:-0.4,y:0.2,z:-0.5,layout_state:'projected',missing_groups:[],missing_reasons:[]},
  {track_id:'b',x:0.5,y:-0.1,z:0.25,layout_state:'partial',missing_groups:['harmony','mood'],missing_reasons:['harmony: missing usable evidence']},
  {track_id:'c',x:null,y:null,z:null,layout_state:'missing',missing_groups:['tempo'],missing_reasons:['tempo: missing usable evidence']}
], edges:[{a:'a',b:'b',distance:0.23,supported_group_count:3}]};
const model = graph.buildGraphModel(tracks, projection);
assert.deepStrictEqual(model.nodes.map(n => n.id), ['a','b','c']);
assert(new Set(model.nodes.map(n => n.position.z)).size > 1, 'true non-coplanar z coordinates expected');
const before = new Map(model.nodes.map(n => [n.id, JSON.stringify(n.position)]));
const visible = graph.applyGraphFilters(model, {tempo:'off',harmony:'hard',energy:'off',genre:'off',mood:'off'});
assert.deepStrictEqual(visible.nodes.map(n => n.id), ['a']);
assert.deepStrictEqual(visible.edges, []);
const cleared = graph.applyGraphFilters(model, {tempo:'off',harmony:'off',energy:'off',genre:'off',mood:'off'});
assert.deepStrictEqual(cleared.nodes.map(n => n.id), ['a','b','c']);
for (const node of cleared.nodes) assert.strictEqual(JSON.stringify(node.position), before.get(node.id));
const missingEvidenceLabel = model.nodes.find(n => n.id === 'c').evidenceLabel;
assert(missingEvidenceLabel.includes('No identity-linked analysis'));
assert(missingEvidenceLabel.includes('No available catalogue location'));
assert(missingEvidenceLabel.includes('Position uses deterministic isolated fallback'));
assert(missingEvidenceLabel.includes('tempo: missing usable evidence'));
const camera = {yaw:0,pitch:0,distance:5,panX:0,panY:0};
graph.orbitCamera(camera, 20, -10); graph.panCamera(camera, 5, -3); graph.zoomCamera(camera, -2);
assert.notStrictEqual(camera.yaw, 0); assert.notStrictEqual(camera.pitch, 0); assert(camera.distance < 5); assert.notStrictEqual(camera.panX, 0);
const point = graph.canvasPoint({clientX:160, clientY:110}, {left:100, top:50, width:600, height:300}, {width:900, height:600});
assert.deepStrictEqual(point, {x:90, y:120});
const bordered = graph.canvasPoint(
  {clientX:162, clientY:112},
  {left:100, top:50, width:604, height:304},
  {width:900, height:600, clientWidth:600, clientHeight:300, clientLeft:2, clientTop:2}
);
assert.deepStrictEqual(bordered, {x:90, y:120});
""";
        if shutil.which('node'):
            subprocess.run(['node', '-e', script, str(APP_JS)], check=True, cwd=REPO_ROOT)
        else:
            source = APP_JS.read_text(encoding='utf-8')
            self.assertIn('function buildGraphModel', source)
            self.assertIn('function applyGraphFilters', source)
            self.assertIn('function orbitCamera', source)
            self.assertIn('function panCamera', source)
            self.assertIn('function zoomCamera', source)
            self.assertIn('function canvasPoint', source)
            self.assertIn('canvasPoint', source[source.index('module.exports'):])
            self.assertIn('module.exports', source)


if __name__ == '__main__':
    unittest.main()
