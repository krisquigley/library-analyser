import json
import sqlite3
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.acceptance.test_explorer_server import APP_ID
from music_analyzer.frameworks.explorer.server import create_server
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository


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
CREATE TABLE track_metadata(track_id TEXT PRIMARY KEY REFERENCES tracks(id), common_json TEXT NOT NULL, tags_json TEXT NOT NULL, warnings_json TEXT NOT NULL);
''')
    db.execute(f'PRAGMA application_id={APP_ID}')
    db.execute('PRAGMA user_version=5')
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
        db.execute('INSERT INTO track_metadata VALUES(?,?,?,?)', (tid, json.dumps([['title', label.removesuffix('.flac')]]), json.dumps([['TITLE', [label.removesuffix('.flac')]]]), json.dumps([])))
        if bpm is not None:
            run_id = 'run-' + suffix
            db.execute('INSERT INTO runs(id,location,status,detail) VALUES(?,?,?,?)', (run_id, '/music/' + label, 'completed', ''))
            db.execute('INSERT INTO run_tracks VALUES(?,?)', (run_id, tid))
            def summary(labels, values):
                return {'labels': list(labels), 'mean': list(values), 'minimum': list(values), 'maximum': list(values), 'coverage': 1.0, 'provisional': True, 'uncertainty': ''}
            stages = [
                ('bpm', {'stage': 'bpm', 'provenance': [], 'uncertainty': '', 'values': [['bpm', bpm]]}),
                ('key', {'stage': 'key', 'provenance': [], 'uncertainty': '', 'values': [['key', key]]}),
                ('energy', {'stage': 'energy', 'provenance': [['emomusic-msd-musicnn-2', 'synthetic-sha256'], ['scale', 'native_valence_arousal_regression']], 'uncertainty': '', 'values': [], 'summary': summary(('arousal', 'valence'), (arousal, valence))}),
                ('genres', {'stage': 'genres', 'provenance': [['genre_discogs400-discogs-effnet-1', 'synthetic-sha256'], ['threshold', '0.5']], 'uncertainty': '', 'values': [], 'summary': summary(('rock', 'jazz'), genre)}),
                ('mood', {'stage': 'mood', 'provenance': [['mtg_jamendo_moodtheme-discogs-effnet-1', 'synthetic-sha256'], ['scale', 'sigmoid_mean_score_0_1']], 'uncertainty': '', 'values': [], 'summary': summary(('relaxing', 'heavy'), mood)}),
            ]
            for stage, payload in stages:
                db.execute('INSERT INTO stages VALUES(?,?,?)', (run_id, stage, json.dumps(payload)))
    db.commit(); db.close()
    SQLiteAnalysisRepository(str(path))
    db = sqlite3.connect(path)
    for tid in ids:
        db.execute("UPDATE track_audio SET duration_seconds=120.0,duration_source='mutagen',status='eligible',reason='' WHERE track_id=?", (tid,))
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
const payload = {selected_mood:'relaxing', available_moods:['relaxing','heavy'], metadata:{}, unpositioned:[{track_id:'c',display_label:'Missing',reasons:['mood: no supported labels available']}], positioned:[
  {track_id:'a', display_label:'Alpha', x:{raw:0.7, normalized:0.7, scale:'native'}, y:{raw:0.2, normalized:0.2, scale:'native'}, z:{label:'BPM', raw:120, normalized:6, scale:'fixed-BPM/20-display-units'}, mood_score:{label:'relaxing',raw:0.9,normalized:0.9}, bpm:120, genres:[['rock',0.6]], genre_threshold:0.5, reasons:[]},
  {track_id:'b', display_label:'Beta', x:{raw:0.3, normalized:0.3, scale:'native'}, y:{raw:0.4, normalized:0.4, scale:'native'}, z:{label:'BPM', raw:130, normalized:6.5, scale:'fixed-BPM/20-display-units'}, mood_score:{label:'relaxing',raw:0.2,normalized:0.2}, bpm:130, genres:[['jazz',0.7]], genre_threshold:0.5, reasons:[]}
], edges:[{a:'a',b:'b',score:0.77,explanation:'axis-independent relatedness',supported_group_count:3}]};
const model = graph.buildMoodGraphModel(payload);
assert.deepStrictEqual(model.nodes.map(n => n.id), ['a','b']);
assert(model.nodes.every(n => Math.abs(n.x) > 1), 'render coordinates are scaled for browser visibility');
assert.strictEqual(model.nodes[0].x, model.nodes[0].axis.x.normalized * 360, 'X display spacing is doubled from the current display origin');
assert.strictEqual(model.nodes[0].fx, model.nodes[0].x, 'fixed X coordinate matches displayed X');
assert.strictEqual(model.nodes[0].y, model.nodes[0].axis.y.normalized * 360, 'Y display spacing is doubled from the current display origin');
assert.strictEqual(model.nodes[0].fy, model.nodes[0].y, 'fixed Y coordinate matches displayed Y');
assert.strictEqual(model.nodes[0].axis.x.raw, 0.7, 'raw X value is unchanged by display scaling');
assert.strictEqual(model.nodes[0].axis.x.normalized, 0.7, 'normalized X value is unchanged by display scaling');
assert.strictEqual(model.nodes[0].axis.y.raw, 0.2, 'raw Y value is unchanged by display scaling');
assert.strictEqual(model.nodes[0].axis.y.normalized, 0.2, 'normalized Y value is unchanged by display scaling');
const before = new Map(model.nodes.map(n => [n.id, JSON.stringify([n.x,n.y,n.z,n.fx,n.fy,n.fz])]));
for (const node of model.nodes) {
  assert.strictEqual(node.z, node.axis.z.normalized * 360, 'fixed BPM depth is half its previous display scale');
  assert.strictEqual(node.fz, node.z, 'fixed simulation depth must match displayed depth');
}
assert.strictEqual(model.nodes[1].z-model.nodes[0].z, 180, '10 BPM retains visible depth at half scale');
const other = graph.buildMoodGraphModel({...payload,selected_mood:'heavy',positioned:payload.positioned.map(n=>({...n,mood_score:{label:'heavy',raw:0.5,normalized:0.5}}))});
assert.deepStrictEqual(other.nodes.map(n=>[n.id,n.x,n.y,n.z,n.fx,n.fy,n.fz]),model.nodes.map(n=>[n.id,n.x,n.y,n.z,n.fx,n.fy,n.fz]));
assert.deepStrictEqual(graph.graphCameraFrame(other.nodes,{width:900,height:700},50),graph.graphCameraFrame(model.nodes,{width:900,height:700},50));
const expandedCamera = graph.graphCameraFrame(model.nodes,{width:900,height:700},50);
assert.deepStrictEqual(expandedCamera.target, {x:180,y:108,z:2250}, 'initial camera frame centers the doubled X/Y display geometry and unchanged Z geometry');
assert.deepStrictEqual(other.links,model.links);
assert.deepStrictEqual(model.genreOptions, ['jazz','rock']);
const visible = graph.applyMoodGraphFilters(model, {bpmMin:119,bpmMax:121,genres:['jazz']});
assert.deepStrictEqual(visible.nodes.map(n => n.id), []);
const genreAny = graph.applyMoodGraphFilters(model, {genres:['jazz','rock']});
assert.deepStrictEqual(genreAny.nodes.map(n => n.id), ['a','b']);
const cleared = graph.applyMoodGraphFilters(model, {});
assert.deepStrictEqual(cleared.nodes.map(n => n.id), ['a','b']);
for (const node of cleared.nodes) assert.strictEqual(JSON.stringify([node.x,node.y,node.z,node.fx,node.fy,node.fz]), before.get(node.id));
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
            for app in (APP_JS, REPO_ROOT / 'music_explorer/frameworks/explorer/assets/app.js'):
                with self.subTest(app=app):
                    subprocess.run(['node', '-e', script, str(app)], check=True, cwd=REPO_ROOT)
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


    @unittest.skipUnless(shutil.which('node'), 'Node is required for graph display spacing tests')
    def test_graph_axis_guides_and_canvas_fallback_use_doubled_xy_display_spacing(self):
        script = r"""
const assert = require('assert');
const app = require(process.argv[1]);
const payload = {selected_mood:'relaxing', available_moods:['relaxing'], metadata:{}, unpositioned:[], positioned:[
  {track_id:'a', display_label:'Alpha', x:{raw:0.2, normalized:0.2, scale:'native'}, y:{raw:0.3, normalized:0.3, scale:'native'}, z:{label:'BPM', raw:120, normalized:6, scale:'fixed-BPM/20-display-units'}, mood_score:{label:'relaxing',raw:0.9,normalized:0.9}, bpm:120, genres:[], reasons:[]},
  {track_id:'b', display_label:'Beta', x:{raw:0.7, normalized:0.7, scale:'native'}, y:{raw:0.5, normalized:0.5, scale:'native'}, z:{label:'BPM', raw:128, normalized:6.4, scale:'fixed-BPM/20-display-units'}, mood_score:{label:'relaxing',raw:0.2,normalized:0.2}, bpm:128, genres:[], reasons:[]}
], edges:[{a:'a',b:'b',score:0.77,explanation:'axis-independent relatedness'}]};
const model = app.buildMoodGraphModel(payload);
const close = (actual, expected, label) => assert(Math.abs(actual - expected) <= 1e-9, `${label}: expected ${expected}, got ${actual}`);
assert.deepStrictEqual(model.nodes.map(n => n.id), ['a','b']);
for (const [node, expected] of [[model.nodes[0], {x:72,y:108,z:2160}], [model.nodes[1], {x:252,y:180,z:2304}]]) {
  close(node.x, expected.x, `${node.id} x display`);
  close(node.fx, expected.x, `${node.id} fx display`);
  close(node.y, expected.y, `${node.id} y display`);
  close(node.fy, expected.y, `${node.id} fy display`);
  assert.strictEqual(node.z, expected.z, `${node.id} z display remains unchanged`);
  assert.strictEqual(node.fz, expected.z, `${node.id} fz display remains unchanged`);
}
assert.deepStrictEqual(model.links.map(l => [l.source,l.target]), [['a','b']], 'links remain attached to the same displayed nodes');
const axes = app.graphAxisSpec(model.nodes);
assert.deepStrictEqual(axes.map(a => a.references), [['0.2','0.7'],['0.3','0.5'],['120.0','128.0']], 'axis labels show native values, not display units');
assert.deepStrictEqual(axes.map(a => [a.key,a.start,a.end]), [
  ['x',{x:54,y:90,z:2142},{x:270,y:90,z:2142}],
  ['y',{x:54,y:90,z:2142},{x:54,y:198,z:2142}],
  ['z',{x:54,y:90,z:2142},{x:54,y:90,z:2322}],
], 'axis visual guides are laid out in doubled X/Y display coordinates with unchanged Z coordinates');
const arcs = [];
const canvas = {clientWidth:600, clientHeight:400, parentElement:null, getContext(){return {clearRect(){}, fillRect(){}, beginPath(){}, arc(x,y,r){arcs.push([x,y,r]);}, fill(){}, set fillStyle(value){}};}};
global.document = {getElementById:id => id === 'map' ? canvas : null, createElement: tag => ({id:'', clientWidth:600, clientHeight:400, parentElement:null, getContext:canvas.getContext})};
app.setStateForTesting({current_track_id:'b'});
app.renderMap(model);
assert.deepStrictEqual(arcs, [[300+72,200-108,5],[300+252,200-180,9]], 'fallback canvas mirrors doubled X/Y display coordinates from the canvas origin');
"""
        for app in (APP_JS, REPO_ROOT / 'music_explorer/frameworks/explorer/assets/app.js'):
            with self.subTest(app=app):
                subprocess.run(['node', '-e', script, str(app)], check=True, cwd=REPO_ROOT)


    def test_graph_filter_source_separates_mood_tracker_control(self):
        for app in (APP_JS, REPO_ROOT / 'music_explorer/frameworks/explorer/assets/app.js'):
            with self.subTest(app=app):
                source = app.read_text(encoding='utf-8')
                controls_source = source[source.index('function buildGraphControls'):source.index('function syncGraphControlOptions')]
                graph_fieldset_source = controls_source[controls_source.index("fs.id='graph-controls'"):controls_source.index("root.append(fs)")]
                self.assertIn("moodFs.id='mood-tracker-controls'", controls_source)
                self.assertIn('Selected mood strength', controls_source)
                self.assertNotIn("mood.id='selected-mood'", graph_fieldset_source)
                self.assertNotIn('Score strip mood', graph_fieldset_source)
                self.assertIn("clear.id='clear-graph-filters'", graph_fieldset_source)
                self.assertNotIn('mood:graphModel.selectedMood', graph_fieldset_source)
                self.assertIn('clearGraphFilters', source[source.index('module.exports'):])
                self.assertIn('getGraphControlsForTesting', source[source.index('module.exports'):])
                self.assertIn('buildGraphControls', source[source.index('module.exports'):])
                self.assertIn('syncGraphControlOptions', source[source.index('module.exports'):])

    @unittest.skipUnless(shutil.which('node'), 'Node is required for graph control DOM tests')
    def test_graph_filters_are_separate_from_mood_tracker_and_bpm_inputs_have_labels(self):
        script = r"""
const assert = require('assert');
const app = require(process.argv[1]);
function makeElement(tag){
  const el = {tagName: tag.toUpperCase(), children: [], parentElement: null, attributes: {}, dataset: {}, id: '', value: '', selectedOptions: [], multiple: false, size: 0, type: '', placeholder: '', textContent: '', onchange: null, onclick: null,
    append(...nodes){for (const node of nodes) { if (node && typeof node === 'object') node.parentElement = this; this.children.push(node); }},
    replaceChildren(...nodes){this.children = []; this.append(...nodes);},
    setAttribute(name, value){this.attributes[name] = String(value);},
    get innerText(){return [this.textContent, ...this.children.map(c => c.innerText || c.textContent || '')].filter(Boolean).join(' ');}
  };
  return el;
}
function findById(root, id){
  if (root.id === id) return root;
  for (const child of root.children || []) { const found = child && typeof child === 'object' ? findById(child, id) : null; if (found) return found; }
  return null;
}
const elements = {};
global.document = {createElement: makeElement, createTextNode: text => ({textContent: String(text), innerText: String(text)}), getElementById: id => elements[id] || null};
const root = makeElement('div');
app.buildGraphControls(root);
const graphControls = findById(root, 'graph-controls');
const moodControls = findById(root, 'mood-tracker-controls');
assert(graphControls, 'graph filter fieldset exists');
assert(moodControls, 'independent mood tracker fieldset exists');
assert(!findById(graphControls, 'selected-mood'), 'selected mood select is not inside graph filters');
assert.strictEqual(findById(moodControls, 'selected-mood').tagName, 'SELECT');
assert.match(graphControls.innerText, /Graph filters/);
for (const [id, name] of [['bpm-min', 'Minimum BPM'], ['bpm-max', 'Maximum BPM']]) {
  const input = findById(graphControls, id);
  assert(input, `${id} input exists`);
  assert.strictEqual(input.attributes['aria-label'], name, `${id} needs a persistent accessible name independent of its placeholder`);
}
assert.doesNotMatch(graphControls.innerText, /mood/i, 'filter copy must not present mood as a graph filter');
assert.match(moodControls.innerText, /Selected mood strength/i);
app.setGraphModelForTesting({availableMoods:['relaxing','heavy'],selectedMood:'relaxing',genreOptions:['jazz','rock'],nodes:[],links:[],unpositioned:[]});
app.syncGraphControlOptions({availableMoods:['relaxing','heavy'],selectedMood:'relaxing',genreOptions:['jazz','rock']});
const mood = findById(root, 'selected-mood');
const genres = findById(root, 'genre-filter');
assert(mood.onchange, 'mood tracker has a change handler');
assert(genres.onchange, 'genre filter has a change handler');
assert(findById(root, 'clear-graph-filters').onclick, 'clear graph filters button is wired');
app.setGraphControlsForTesting({mood:'heavy', bpmMin:90, bpmMax:150, genres:['jazz']});
assert.strictEqual(app.graphQueryFromControls(), '?mood=heavy');
assert.deepStrictEqual(app.getGraphControlsForTesting().genres, ['jazz']);
app.clearGraphFilters();
assert.strictEqual(app.getGraphControlsForTesting().mood, 'heavy', 'clearing graph filters preserves independent mood tracker selection');
assert.deepStrictEqual(app.getGraphControlsForTesting().genres, []);
assert.strictEqual(app.getGraphControlsForTesting().bpmMin, null);
assert.strictEqual(app.graphQueryFromControls(), '?mood=heavy');
"""
        for app in (APP_JS, REPO_ROOT / 'music_explorer/frameworks/explorer/assets/app.js'):
            with self.subTest(app=app):
                subprocess.run(['node', '-e', script, str(app)], check=True, cwd=REPO_ROOT)



    @unittest.skipUnless(shutil.which('node'), 'Node is required for graph filter render tests')
    def test_loaded_graph_filters_recompute_visible_graph_without_fetching_graph_again(self):
        script = r"""
const assert = require('assert');
const app = require(process.argv[1]);
function makeElement(tag){
  const el = {tagName:tag.toUpperCase(), children:[], attributes:{}, dataset:{}, className:'', id:'', value:'', selected:false, selectedOptions:[], multiple:false, size:0, type:'', placeholder:'', textContent:'', onclick:null, onchange:null,
    append(...nodes){for (const node of nodes) { if (node && typeof node === 'object') node.parentElement = this; this.children.push(node); }},
    replaceChildren(...nodes){this.children=[]; this.append(...nodes);},
    setAttribute(name,value){this.attributes[name]=String(value);},
    removeAttribute(name){delete this.attributes[name];},
    getContext(){return {clearRect(){}, fillRect(){}, beginPath(){}, moveTo(){}, lineTo(){}, stroke(){}, arc(){}, fill(){}};},
    get innerText(){return [this.textContent, ...this.children.map(c=>c.innerText || c.textContent || '')].filter(Boolean).join(' ');}
  };
  return el;
}
function findById(root,id){ if(root.id===id) return root; for(const child of root.children||[]){const found=child&&typeof child==='object'?findById(child,id):null; if(found) return found;} return null; }
const elements = {'graph-load-status': makeElement('section'), graph3d: makeElement('div'), 'mood-strip': null, 'mood-strip-picker': null, 'mood-strip-value': null};
global.document = {createElement: makeElement, getElementById:id=>elements[id]||null, querySelectorAll:()=>[]};
global.requestAnimationFrame = cb => cb();
let graphRequests = 0;
global.fetch = async path => {
  if (String(path).startsWith('/api/mood-axis-graph')) graphRequests += 1;
  return {ok:true, json:async()=>({selected_mood:'relaxing', available_moods:['relaxing','heavy'], positioned:[
    {track_id:'a', display_label:'Alpha', x:{raw:0.7, normalized:0.7, scale:'native'}, y:{raw:0.2, normalized:0.2, scale:'native'}, z:{label:'BPM', raw:120, normalized:6, scale:'fixed'}, mood_score:{label:'relaxing',raw:0.9}, bpm:120, genres:[['rock',0.6]], reasons:[]},
    {track_id:'b', display_label:'Beta', x:{raw:0.3, normalized:0.3, scale:'native'}, y:{raw:0.4, normalized:0.4, scale:'native'}, z:{label:'BPM', raw:130, normalized:6.5, scale:'fixed'}, mood_score:{label:'relaxing',raw:0.2}, bpm:130, genres:[['jazz',0.7]], reasons:[]}
  ], edges:[{a:'a',b:'b',score:0.5}], unpositioned:[]})};
};
const root = makeElement('div');
app.buildGraphControls(root);
const bpmMin = findById(root, 'bpm-min');
const genre = findById(root, 'genre-filter');
const clear = findById(root, 'clear-graph-filters');
global.ForceGraph3D = undefined;
(async()=>{
  await app.loadGraph();
  assert.strictEqual(graphRequests, 1, 'Load graph fetches graph once');
  assert.deepStrictEqual(app.getVisibleGraphForTesting().nodes.map(n=>n.id), ['a','b']);
  bpmMin.value = '125';
  bpmMin.onchange();
  assert.strictEqual(graphRequests, 1, 'BPM filtering must not reload graph');
  assert.deepStrictEqual(app.getVisibleGraphForTesting().nodes.map(n=>n.id), ['b']);
  genre.selectedOptions = [{value:'jazz'}];
  genre.onchange();
  assert.strictEqual(graphRequests, 1, 'genre filtering must not reload graph');
  assert.deepStrictEqual(app.getVisibleGraphForTesting().nodes.map(n=>n.id), ['b']);
  clear.onclick();
  assert.strictEqual(graphRequests, 1, 'clearing graph filters must not reload graph');
  assert.deepStrictEqual(app.getVisibleGraphForTesting().nodes.map(n=>n.id), ['a','b']);
  assert.strictEqual(app.getGraphControlsForTesting().bpmMin, null);
})().catch(error=>{console.error(error); process.exit(1);});
"""
        for app in (APP_JS, REPO_ROOT / 'music_explorer/frameworks/explorer/assets/app.js'):
            with self.subTest(app=app):
                subprocess.run(['node', '-e', script, str(app)], check=True, cwd=REPO_ROOT)

    def test_load_graph_uses_api_graph_status_for_read_only_snapshot_copy(self):
        for app in (APP_JS, REPO_ROOT / 'music_explorer/frameworks/explorer/assets/app.js'):
            with self.subTest(app=app):
                source = app.read_text(encoding='utf-8')
                start = source.index('async function loadGraph()')
                end = source.index('function applyCurrentGraphFilters()', start)
                load_graph = source[start:end]
                self.assertIn('graphStatusMessage(graphModel.metadata.graph_status', load_graph)
                self.assertIn('graphLoadState={...graphLoadState,status:statusCopy.status,message:statusCopy.message', load_graph)
                helper_start = source.index('function graphStatusMessage(')
                helper_end = source.index('function applyCurrentGraphFilters()', helper_start)
                helper = source[helper_start:helper_end]
                for state in ('stale', 'build_needed', 'failed', 'building'):
                    self.assertIn(state, helper)
                self.assertIn('music-analyzer graph build --database DB', helper)
                self.assertNotIn('.reason', helper)
                self.assertNotIn('.action', helper)
                ready_index = helper.index("case 'ready'")
                self.assertLess(ready_index, helper.index('Graph ready'))

    @unittest.skipUnless(shutil.which('node'), 'Node is required for graph status DOM tests')
    def test_load_graph_displays_api_graph_status_without_misleading_ready_copy(self):
        script = r"""
const assert = require('assert');
const app = require(process.argv[1]);
function makeElement(tag){
  const el = {tagName:tag.toUpperCase(), children:[], attributes:{}, dataset:{}, className:'', id:'', value:'', selected:false, selectedOptions:[], multiple:false, size:0, type:'', placeholder:'', textContent:'', onclick:null, onchange:null, parentElement:null, clientWidth:900, clientHeight:700,
    append(...nodes){for (const node of nodes) { if (node && typeof node === 'object') node.parentElement = this; this.children.push(node); }},
    replaceChildren(...nodes){this.children=[]; this.textContent=''; this.append(...nodes);},
    setAttribute(name,value){this.attributes[name]=String(value);},
    removeAttribute(name){delete this.attributes[name];},
    getContext(){return {clearRect(){}, fillRect(){}, beginPath(){}, moveTo(){}, lineTo(){}, stroke(){}, arc(){}, fill(){}};},
    get innerText(){return [this.textContent, ...this.children.map(c=>c.innerText || c.textContent || '')].filter(Boolean).join(' ');}
  };
  return el;
}
const statusPanel = makeElement('section');
const elements = {'graph-load-status': statusPanel, graph3d: makeElement('div'), map: makeElement('canvas'), 'mood-strip': null, 'mood-strip-picker': null, 'mood-strip-value': null};
global.document = {createElement: makeElement, getElementById:id=>elements[id]||null, querySelectorAll:()=>[]};
global.requestAnimationFrame = cb => cb();
global.ForceGraph3D = undefined;
const node = {track_id:'a', display_label:'Alpha', x:{raw:0.7, normalized:0.7, scale:'native'}, y:{raw:0.2, normalized:0.2, scale:'native'}, z:{label:'BPM', raw:120, normalized:6, scale:'fixed'}, mood_score:{label:'relaxing',raw:0.9}, bpm:120, genres:[], reasons:[]};
async function loadWithStatus(graphStatus){
  global.fetch = async path => ({ok:true, json:async()=>({selected_mood:'relaxing', available_moods:['relaxing'], positioned:[node], edges:[], unpositioned:[], metadata:{graph_status:graphStatus}})});
  await app.loadGraph();
  return statusPanel.innerText;
}
(async()=>{
  const ready = await loadWithStatus({state:'ready'});
  assert.match(ready, /Graph ready: 1 positioned tracks/);
  for (const [state, label] of [['stale', 'stale'], ['build_needed', 'needs a build'], ['failed', 'failed'], ['building', 'building']]) {
    const text = await loadWithStatus({state, reason:'contains <img src=x onerror=alert(1)> and /Users/alice/private.sqlite', action:'run hidden command'});
    assert.doesNotMatch(text, /Graph ready/, `${state} response must not be labelled ready`);
    assert.match(text, new RegExp(label, 'i'), `${state} response explains the status`);
    assert.match(text, /music-analyzer graph build --database DB/, `${state} response gives the explicit read-only rebuild command`);
    assert.doesNotMatch(text, /private\.sqlite|Users\/alice|hidden command/, `${state} response must not leak API paths or commands`);
  }
})().catch(error=>{console.error(error); process.exit(1);});
"""
        for app in (APP_JS, REPO_ROOT / 'music_explorer/frameworks/explorer/assets/app.js'):
            with self.subTest(app=app):
                subprocess.run(['node', '-e', script, str(app)], check=True, cwd=REPO_ROOT)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for mood tracker reload tests')
    def test_mood_tracker_change_reloads_ready_graph_but_not_before_initial_load(self):
        script = r"""
const assert = require('assert');
const app = require(process.argv[1]);
function makeElement(tag){
  const el = {tagName:tag.toUpperCase(), children:[], attributes:{}, dataset:{}, className:'', id:'', value:'', selected:false, selectedOptions:[], multiple:false, size:0, type:'', placeholder:'', textContent:'', onclick:null, onchange:null, parentElement:null, clientWidth:900, clientHeight:700,
    append(...nodes){for (const node of nodes) { if (node && typeof node === 'object') node.parentElement = this; this.children.push(node); }},
    replaceChildren(...nodes){this.children=[]; this.textContent=''; this.append(...nodes);},
    setAttribute(name,value){this.attributes[name]=String(value);},
    removeAttribute(name){delete this.attributes[name];},
    getContext(){return {clearRect(){}, fillRect(){}, beginPath(){}, arc(){}, fill(){}};},
    get innerText(){return [this.textContent, ...this.children.map(c=>c.innerText || c.textContent || '')].filter(Boolean).join(' ');}
  };
  return el;
}
function findById(root,id){ if(root.id===id) return root; for(const child of root.children||[]){const found=child&&typeof child==='object'?findById(child,id):null; if(found) return found;} return null; }
const elements = {'graph-load-status': makeElement('section'), graph3d: makeElement('div'), 'mood-strip': null, 'mood-strip-picker': null, 'mood-strip-value': null};
global.document = {createElement: makeElement, getElementById:id=>elements[id]||null, querySelectorAll:()=>[]};
global.requestAnimationFrame = cb => cb();
global.ForceGraph3D = undefined;
const root = makeElement('div');
app.buildGraphControls(root);
const mood = findById(root, 'selected-mood');
let requests = [];
global.fetch = async path => {
  requests.push(String(path));
  const url = new URL(String(path), 'http://example.test');
  const selectedMood = url.searchParams.get('mood') || 'relaxing';
  assert.strictEqual(url.searchParams.get('contract'), 'v2', 'graph reloads must opt into the compact v2 contract');
  const heavy = selectedMood === 'heavy';
  return {ok:true, json:async()=>({
    dto_version:'mood-axis-graph-compact-v1',
    selected_mood:selectedMood,
    available_moods:['relaxing','heavy'],
    metadata:{graph_status:{state:'ready'}},
    nodes:[
      {id:'a', label:'Alpha', axis:{x:{label:'valence',raw:0.7, normalized:0.7, scale:'native'}, y:{label:'arousal',raw:0.2, normalized:0.2, scale:'native'}, z:{label:'BPM', raw:120, normalized:6, scale:'fixed'}}, mood_score:{label:selectedMood,raw:heavy?0.8:0.1,normalized:heavy?0.8:0.1}, bpm:120, genres:[], reasons:[]}
    ],
    links:[],
    unpositioned:[]
  })};
};
(async()=>{
  mood.value = 'heavy';
  const before = mood.onchange();
  if (before && before.then) await before;
  assert.deepStrictEqual(requests, [], 'changing the mood before Load graph only stores the choice and never auto-fetches');
  await app.loadGraph();
  assert.deepStrictEqual(requests, ['/api/mood-axis-graph?mood=heavy&contract=v2'], 'manual Load graph uses the stored mood and compact contract');
  assert.strictEqual(app.getVisibleGraphForTesting().nodes[0].moodScore.label, 'heavy');
  mood.value = 'relaxing';
  const after = mood.onchange();
  if (after && after.then) await after;
  assert.deepStrictEqual(requests, ['/api/mood-axis-graph?mood=heavy&contract=v2','/api/mood-axis-graph?mood=relaxing&contract=v2'], 'changing the mood after the graph is ready reloads compact graph data');
  assert.strictEqual(app.getVisibleGraphForTesting().nodes[0].moodScore.label, 'relaxing');
  assert.strictEqual(app.buildMoodStrip(app.getVisibleGraphForTesting(), null)[0].score, 0.1, 'strip uses the reloaded mood score');
})().catch(error=>{console.error(error); process.exit(1);});
"""
        for app in (APP_JS, REPO_ROOT / 'music_explorer/frameworks/explorer/assets/app.js'):
            with self.subTest(app=app):
                subprocess.run(['node', '-e', script, str(app)], check=True, cwd=REPO_ROOT)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for relatedness alpha tests')
    def test_relatedness_link_alpha_reflects_clamped_score_and_notes_explain_it(self):
        script = r"""
const assert = require('assert');
const app = require(process.argv[1]);
assert.strictEqual(app.relatednessLinkAlpha({score:0}), 0.18);
assert.strictEqual(app.relatednessLinkAlpha({score:1}), 0.72);
assert.strictEqual(app.relatednessLinkAlpha({score:-2}), 0.18);
assert.strictEqual(app.relatednessLinkAlpha({score:2}), 0.72);
assert.strictEqual(app.relatednessLinkAlpha({}), 0.18);
assert.strictEqual(app.relatednessLinkAlpha({score:'not-a-number'}), 0.18);
assert(app.relatednessLinkAlpha({score:0.9}) > app.relatednessLinkAlpha({score:0.2}));
assert.strictEqual(app.graphRelatednessLegend(), 'Link alpha reflects axis-independent relatedness strength from existing stored summaries; higher-score links are more opaque.');
"""
        subprocess.run(['node', '-e', script, str(APP_JS)], check=True, cwd=REPO_ROOT)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for force graph configuration tests')
    def test_force_graph_receives_per_link_rgba_and_numeric_global_opacity(self):
        script = r"""
const assert = require('assert');
const fs = require('fs'), vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const bundle = fs.readFileSync(process.argv[2], 'utf8');
// Verify the bundled renderer actually multiplies its numeric global opacity by the
// alpha parsed from the per-link color; a callback in linkOpacity becomes NaN.
assert(bundle.includes('e.linkOpacity*mf(c)'), 'vendored bundle must multiply global opacity by color alpha');
assert(bundle.includes('linkColor:{default:"color"}'));
const context = {module:{exports:{}}, console, URLSearchParams};
vm.createContext(context);
vm.runInContext(source, context);
const settings = {};
const graph = new Proxy({}, {get(_, key) {
  if (key === 'camera') return () => ({fov:60});
  return value => { settings[key] = value; return graph; };
}});
context.ForceGraph3D = () => () => graph;
context.document = {getElementById:id => id === 'graph3d' ? {clientWidth:900,clientHeight:500} : null};
const data = {nodes:[{id:'a',x:0,y:0,z:0},{id:'b',x:1,y:1,z:1}],links:[
  {source:'a',target:'b',score:-2},{source:'a',target:'b',score:0.5},
  {source:'a',target:'b',score:2},{source:'a',target:'b',score:'bad'}],unpositioned:[]};
context.renderMap(data);
assert.strictEqual(typeof settings.linkOpacity, 'number', 'bundled graph expects numeric global opacity');
assert.strictEqual(settings.linkOpacity, 1);
assert.strictEqual(typeof settings.linkColor, 'function');
const alpha = link => {
  const color = settings.linkColor(link);
  assert(/^rgba\(\d+,\d+,\d+,0\.\d+\)$/.test(color), color);
  return Number(color.slice(color.lastIndexOf(',')+1, -1)) * settings.linkOpacity;
};
assert.deepStrictEqual(data.links.map(alpha), [0.18,0.45,0.72,0.18]);
"""
        for app in (APP_JS, REPO_ROOT / 'music_explorer/frameworks/explorer/assets/app.js'):
            with self.subTest(app=app):
                source = app.read_text(encoding='utf-8')
                self.assertIn('graphRelatednessLegend', source)
                subprocess.run(['node', '-e', script, str(app), str(app.parent / 'vendor/3d-force-graph/3d-force-graph.min.js')], check=True, cwd=REPO_ROOT)


    @unittest.skipUnless(shutil.which('node'), 'Node is required for selected node halo renderer tests')
    def test_selected_node_halo_syncs_without_replacing_graph_data(self):
        script = r"""
const assert = require('assert');
const fs = require('fs'), vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const context = {module:{exports:{}}, console, URLSearchParams, setTimeout, clearTimeout};
vm.createContext(context);
vm.runInContext(source, context);
const scene = makeScene();
const graph = makeGraph(scene);
context.ForceGraph3D = () => () => graph;
context.document = {getElementById:id => id === 'graph3d' ? {clientWidth:900,clientHeight:500} : null, querySelectorAll:() => []};
const data = sampleGraph();
context.setGraphModelForTesting({...data, metadata:{}});
context.setVisibleGraphForTesting(data);
context.renderMap(data);
assert.strictEqual(graph.graphDataCalls, 1, 'initial render loads graph data once');
context.setStateForTesting({current_track_id:'a'});
context.updateSelectedTrackVisuals();
let halos = selectedNodeHalos(scene);
assert.strictEqual(halos.length, 1, 'selecting node a adds exactly one halo');
assert.strictEqual(halos[0].userData.trackId, 'a');
const aHalo = halos[0];
context.setStateForTesting({current_track_id:'b'});
context.updateSelectedTrackVisuals();
halos = selectedNodeHalos(scene);
assert.strictEqual(halos.length, 1, 'changing selection replaces stale halo with exactly one current halo');
assert.strictEqual(halos[0].userData.trackId, 'b');
assert(aHalo.disposed, 'old halo is removed/disposed when selection changes');
context.setStateForTesting({current_track_id:null});
context.updateSelectedTrackVisuals();
assert.strictEqual(selectedNodeHalos(scene).length, 0, 'clearing selection removes halo');
assert.strictEqual(graph.graphDataCalls, 1, 'selection-only halo sync must not replace graph data');
assert.deepStrictEqual(data.nodes.map(n => Object.keys(n).sort()), sampleGraph().nodes.map(n => Object.keys(n).sort()), 'halo sync does not add coordinates/properties to DTO nodes');
assert.deepStrictEqual(data.links, sampleGraph().links, 'halo sync does not mutate links');
function sampleGraph(){return {nodes:[
  {id:'a',label:'Alpha',x:10,y:20,z:30,fx:10,fy:20,fz:30,color:'#336699',axis:{x:{raw:0.1,scale:'native'},y:{raw:0.2,scale:'native'},z:{label:'BPM',raw:120,scale:'fixed'}},moodScore:{label:'relaxing',raw:0.8}},
  {id:'b',label:'Beta',x:40,y:50,z:60,fx:40,fy:50,fz:60,color:'#993366',axis:{x:{raw:0.3,scale:'native'},y:{raw:0.4,scale:'native'},z:{label:'BPM',raw:130,scale:'fixed'}},moodScore:{label:'relaxing',raw:0.2}}
], links:[{source:'a',target:'b',score:0.7}], unpositioned:[]};}
function makeScene(){return {children:[], add(obj){this.children.push(obj);}, remove(obj){this.children=this.children.filter(child => child !== obj); obj.disposed = true; if (obj.geometry && obj.geometry.dispose) obj.geometry.dispose(); if (obj.material && obj.material.dispose) obj.material.dispose();}};}
function makeGraph(scene){let data = {nodes:[],links:[]}; const graph = {graphDataCalls:0, scene(){return scene;}, camera(){return {fov:60};}, graphData(next){if(arguments.length){this.graphDataCalls += 1; data = next; return graph;} return data;}, refresh(){return graph;}}; for (const name of ['enableNodeDrag','cooldownTicks','nodeId','nodeRelSize','nodeLabel','nodeColor','nodeVal','linkLabel','linkOpacity','linkColor','linkWidth','onNodeClick','numDimensions','d3AlphaDecay','d3VelocityDecay','cameraPosition','width','height']) graph[name] = () => graph; return graph;}
function selectedNodeHalos(scene){return scene.children.filter(obj => obj.name === 'selected-node-halo' || (obj.userData && obj.userData.role === 'selected-node-halo'));}
"""
        for app in (APP_JS, REPO_ROOT / 'music_explorer/frameworks/explorer/assets/app.js'):
            with self.subTest(app=app):
                subprocess.run(['node', '-e', script, str(app)], check=True, cwd=REPO_ROOT)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for selected node halo material tests')
    def test_selected_node_halo_uses_translucent_non_pickable_shell_material(self):
        script = r"""
const assert = require('assert');
const fs = require('fs'), vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const context = {module:{exports:{}}, console, URLSearchParams, setTimeout, clearTimeout};
vm.createContext(context);
vm.runInContext(source, context);
const scene = makeSceneWithThree();
const graph = makeGraph(scene);
context.ForceGraph3D = () => () => graph;
context.document = {getElementById:id => id === 'graph3d' ? {clientWidth:900,clientHeight:500} : null, querySelectorAll:() => []};
const data = {nodes:[{id:'a',label:'Alpha',x:10,y:20,z:30,fx:10,fy:20,fz:30,color:'#336699',axis:{x:{raw:0.1,scale:'native'},y:{raw:0.2,scale:'native'},z:{label:'BPM',raw:120,scale:'fixed'}},moodScore:{label:'relaxing',raw:0.8}}], links:[], unpositioned:[]};
context.setGraphModelForTesting({...data, metadata:{}});
context.setVisibleGraphForTesting(data);
context.renderMap(data);
context.setStateForTesting({current_track_id:'a'});
context.updateSelectedTrackVisuals();
const halo = scene.children.find(obj => obj.name === 'selected-node-halo' || (obj.userData && obj.userData.role === 'selected-node-halo'));
assert(halo, 'selected node halo mesh is added to the graph scene');
assert(Math.abs((halo.geometry.radius / scene.selectedNodeMesh.geometry.radius) - 1.3) < 0.05, `halo radius ${halo.geometry.radius} should be about 1.3x actual selected node sphere radius ${scene.selectedNodeMesh.geometry.radius}`);
assert.strictEqual(halo.material.transparent, true, 'halo shell material is transparent');
assert(Math.abs(halo.material.opacity - 0.25) <= 0.03, `halo opacity ${halo.material.opacity} should be approximately 25%`);
assert.strictEqual(halo.material.depthWrite, false, 'halo should not occlude graph geometry in depth buffer');
assert.notStrictEqual(halo.material.color, '#336699', 'halo color should contrast with the selected node color');
assert.strictEqual(typeof halo.raycast, 'function', 'halo supplies a raycast override');
const intersections = [];
halo.raycast({}, intersections);
assert.deepStrictEqual(intersections, [], 'halo raycast is a no-op and cannot intercept picking');
function makeSceneWithThree(){
  class Geometry { constructor(radius){this.radius = radius;} dispose(){this.disposed = true;} }
  class Material { constructor(params){Object.assign(this, params);} dispose(){this.disposed = true;} }
  class Mesh { constructor(geometry, material){this.geometry = geometry; this.material = material; this.position = {set:(x,y,z)=>{this.x=x; this.y=y; this.z=z;}}; this.userData = {}; this.name = ''; this.scale = {setScalar:value=>{this.scale.value=value;}};} }
  Mesh.prototype.isMesh = true;
  const selectedNodeMesh = new Mesh(new Geometry(16), new Material({color:'#336699'}));
  selectedNodeMesh.__THREE = {SphereGeometry: Geometry, MeshBasicMaterial: Material, Mesh};
  selectedNodeMesh.userData = {id:'a'};
  selectedNodeMesh.__data = {id:'a'};
  const scene = {children:[selectedNodeMesh], selectedNodeMesh, constructor:function Group(){this.children=[]; this.add=o=>this.children.push(o);}, add(obj){this.children.push(obj);}, remove(obj){this.children=this.children.filter(child => child !== obj);}};
  return scene;
}
function makeGraph(scene){let data = {nodes:[],links:[]}; const graph = {scene(){return scene;}, camera(){return {fov:60};}, graphData(next){if(arguments.length){data = next; return graph;} return data;}, refresh(){return graph;}}; for (const name of ['enableNodeDrag','cooldownTicks','nodeId','nodeRelSize','nodeLabel','nodeColor','nodeVal','linkLabel','linkOpacity','linkColor','linkWidth','onNodeClick','numDimensions','d3AlphaDecay','d3VelocityDecay','cameraPosition','width','height']) graph[name] = () => graph; return graph;}
"""
        for app in (APP_JS, REPO_ROOT / 'music_explorer/frameworks/explorer/assets/app.js'):
            with self.subTest(app=app):
                subprocess.run(['node', '-e', script, str(app)], check=True, cwd=REPO_ROOT)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for selected node halo filter tests')
    def test_selected_node_halo_removed_when_filtered_node_not_visible(self):
        script = r"""
const assert = require('assert');
const fs = require('fs'), vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const context = {module:{exports:{}}, console, URLSearchParams, setTimeout, clearTimeout};
vm.createContext(context);
vm.runInContext(source, context);
const scene = makeScene();
const graph = makeGraph(scene);
context.ForceGraph3D = () => () => graph;
context.document = {getElementById:id => id === 'graph3d' ? {clientWidth:900,clientHeight:500} : null, querySelectorAll:() => []};
const all = sampleGraph();
context.setGraphModelForTesting({...all, metadata:{}});
context.setVisibleGraphForTesting(all);
context.renderMap(all);
context.setStateForTesting({current_track_id:'a'});
context.updateSelectedTrackVisuals();
assert.strictEqual(selectedNodeHalos(scene).length, 1, 'precondition: selected visible node has a halo');
const filtered = {nodes:[all.nodes[1]], links:[], unpositioned:[]};
context.setVisibleGraphForTesting(filtered);
context.renderMap(filtered);
assert.strictEqual(context.getStateForTesting().current_track_id, 'a', 'filtering can leave current selection set to a hidden track');
assert.strictEqual(selectedNodeHalos(scene).length, 0, 'halo is removed when selected node is no longer visible');
function sampleGraph(){return {nodes:[
  {id:'a',label:'Alpha',x:10,y:20,z:30,fx:10,fy:20,fz:30,color:'#336699',axis:{x:{raw:0.1,scale:'native'},y:{raw:0.2,scale:'native'},z:{label:'BPM',raw:120,scale:'fixed'}},moodScore:{label:'relaxing',raw:0.8}},
  {id:'b',label:'Beta',x:40,y:50,z:60,fx:40,fy:50,fz:60,color:'#993366',axis:{x:{raw:0.3,scale:'native'},y:{raw:0.4,scale:'native'},z:{label:'BPM',raw:130,scale:'fixed'}},moodScore:{label:'relaxing',raw:0.2}}
], links:[{source:'a',target:'b',score:0.7}], unpositioned:[]};}
function makeScene(){return {children:[], add(obj){this.children.push(obj);}, remove(obj){this.children=this.children.filter(child => child !== obj); obj.disposed = true;}};}
function makeGraph(scene){let data = {nodes:[],links:[]}; const graph = {scene(){return scene;}, camera(){return {fov:60};}, graphData(next){if(arguments.length){data = next; return graph;} return data;}, refresh(){return graph;}}; for (const name of ['enableNodeDrag','cooldownTicks','nodeId','nodeRelSize','nodeLabel','nodeColor','nodeVal','linkLabel','linkOpacity','linkColor','linkWidth','onNodeClick','numDimensions','d3AlphaDecay','d3VelocityDecay','cameraPosition','width','height']) graph[name] = () => graph; return graph;}
function selectedNodeHalos(scene){return scene.children.filter(obj => obj.name === 'selected-node-halo' || (obj.userData && obj.userData.role === 'selected-node-halo'));}
"""
        for app in (APP_JS, REPO_ROOT / 'music_explorer/frameworks/explorer/assets/app.js'):
            with self.subTest(app=app):
                subprocess.run(['node', '-e', script, str(app)], check=True, cwd=REPO_ROOT)


    @unittest.skipUnless(shutil.which('node'), 'Node is required for tracks table tests')
    def test_tracks_render_as_searchable_title_artist_table(self):
        script = r"""
const assert = require('assert');
const app = require(process.argv[1]);
function makeElement(tag){
  return {tagName:tag.toUpperCase(), children:[], attributes:{}, dataset:{}, className:'', value:'', textContent:'', onclick:null, oninput:null,
    append(...nodes){this.children.push(...nodes);},
    replaceChildren(...nodes){this.children=[...nodes]; this.textContent='';},
    setAttribute(name,value){this.attributes[name]=String(value);},
    getAttribute(name){return this.attributes[name] || null;},
    removeAttribute(name){delete this.attributes[name];},
    get innerText(){return [this.textContent, ...this.children.map(c=>c.innerText || c.textContent || '')].filter(Boolean).join(' ');}
  };
}
const tracks = makeElement('div');
const search = makeElement('input');
const elements = {tracks, 'track-search': search};
global.document = {createElement: makeElement, getElementById(id){return elements[id] || null;}, querySelectorAll(){return [];}};
global.setTimeout = fn => { fn(); return 1; };
global.clearTimeout = () => {};
let requested = [];
global.fetch = async path => {
  requested.push(String(path));
  const url = new URL(String(path), 'http://example.test');
  const query = (url.searchParams.get('query') || '').toLowerCase();
  const all = [
    {handle:'one', display_label:'Filename One.flac', title:'Bright Song', artist:'Alice'},
    {handle:'two', display_label:'Filename Two.flac', title:'Quiet Tune', artist:'Bob'},
    {handle:'three', display_label:'Fallback.flac', artist:'Unknown artist'}
  ];
  const filtered = query ? all.filter(t => `${t.title || t.display_label} ${t.artist || 'Unknown artist'}`.toLowerCase().includes(query)) : all;
  return {ok:true, json:async()=>({tracks:filtered, metadata:{track_count:filtered.length}})};
};
app.setStateForTesting({current_track_id:'two'});
app.renderTracks([
  {handle:'one', display_label:'Filename One.flac', title:'Bright Song', artist:'Alice'},
  {handle:'two', display_label:'Filename Two.flac', title:'Quiet Tune', artist:'Bob'},
  {handle:'three', display_label:'Fallback.flac', artist:'Unknown artist'}
]);
assert.strictEqual(tracks.children[0].tagName, 'TABLE');
let table = tracks.children[0];
assert.strictEqual(table.children[1].children[0].children[0].textContent, 'Title');
assert.strictEqual(table.children[1].children[0].children[1].textContent, 'Artist');
let tbody = table.children[2];
assert.strictEqual(tbody.children.length, 3);
assert.strictEqual(tbody.children[1].className, 'current');
assert.strictEqual(tbody.children[1].children[0].children[0].getAttribute('aria-current'), 'true');
assert.strictEqual(tbody.children[0].children[0].children[0].getAttribute('aria-current'), null);
assert(tbody.children[0].innerText.includes('Bright Song') && tbody.children[0].innerText.includes('Alice'));
assert(tbody.children[2].innerText.includes('Fallback.flac') && tbody.children[2].innerText.includes('Unknown artist'));
async function flushSummarySearch(){for(let i=0;i<8;i++) await Promise.resolve();}
(async()=>{
  search.value = 'alice'; search.oninput(); await flushSummarySearch();
  assert(requested.at(-1).includes('/api/tracks/summary?limit=100&order=title&query=alice'));
  table = tracks.children[0]; tbody = table.children[2];
  assert.strictEqual(tbody.children.length, 1);
  assert(tbody.children[0].innerText.includes('Bright Song'));
  search.value = 'QUIET'; search.oninput(); await flushSummarySearch();
  table = tracks.children[0]; tbody = table.children[2];
  assert.strictEqual(tbody.children.length, 1);
  assert(tbody.children[0].innerText.includes('Quiet Tune'));
  search.value = 'Filename'; search.oninput(); await flushSummarySearch();
  table = tracks.children[0]; tbody = table.children[2];
  assert.strictEqual(tbody.children.length, 0, 'server-side summary search only matches title and artist');
  assert(tracks.innerText.includes('No tracks match your search'));
  search.value = ''; search.oninput(); await flushSummarySearch();
  table = tracks.children[0]; tbody = table.children[2];
  assert.strictEqual(tbody.children.length, 3);
})().catch(error=>{console.error(error); process.exit(1);});
"""
        subprocess.run(['node', '-e', script, str(APP_JS)], check=True, cwd=REPO_ROOT)

    def test_track_summary_source_uses_next_cursor_and_load_more_without_unbounded_list(self):
        for package in ('music_analyzer', 'music_explorer'):
            with self.subTest(package=package):
                source = (REPO_ROOT / package / 'frameworks/explorer/assets/app.js').read_text(encoding='utf-8')
                self.assertIn("params.set('cursor',cursor)", source)
                self.assertIn("Load more tracks", source)
                self.assertIn("Showing ${tracks.length} of ${total}", source)
                self.assertIn('next_cursor', source[source.index('function renderTracks'):])
                self.assertNotIn('/api/tracks?limit=all', source)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for track pagination DOM tests')
    def test_summary_list_load_more_uses_next_cursor_appends_and_preserves_selection(self):
        script = r"""
const assert = require('assert');
const app = require(process.argv[1]);
function makeElement(tag){
  return {tagName:tag.toUpperCase(), children:[], attributes:{}, dataset:{}, className:'', value:'', textContent:'', onclick:null, oninput:null, hidden:false, disabled:false, type:'', id:'',
    append(...nodes){this.children.push(...nodes);},
    replaceChildren(...nodes){this.children=[...nodes]; this.textContent='';},
    setAttribute(name,value){this.attributes[name]=String(value); if(name==='aria-label') this.ariaLabel=String(value);},
    getAttribute(name){return this.attributes[name] || null;},
    removeAttribute(name){delete this.attributes[name];},
    get innerText(){return [this.textContent, ...this.children.map(c=>c.innerText || c.textContent || '')].filter(Boolean).join(' ');}
  };
}
const tracks = makeElement('div');
const search = makeElement('input');
const elements = {tracks, 'track-search': search};
global.document = {createElement: makeElement, getElementById(id){return elements[id] || null;}, querySelectorAll(){return [];}};
let fetches = [];
global.fetch = async path => {
  fetches.push(String(path));
  if (String(path).includes('cursor=after-100')) return {ok:true, json:async()=>({tracks:[{handle:'selected', title:'Title 00100', artist:'Artist'}, {handle:'later', title:'Title 00101', artist:'Artist'}], metadata:{track_count:102}, next_cursor:null})};
  return {ok:true, json:async()=>({tracks:[{handle:'first', title:'Title 00000', artist:'Artist'}], metadata:{track_count:102}, next_cursor:'after-100'})};
};
(async()=>{
  app.setStateForTesting({current_track_id:'selected'});
  await app.loadTrackSummaryPage('');
  assert.deepStrictEqual(fetches, ['/api/tracks/summary?limit=100&order=title']);
  assert(tracks.innerText.includes('Showing 1 of 102'));
  let loadMore = tracks.children.find(child => child.tagName === 'NAV').children[0];
  assert.strictEqual(loadMore.textContent, 'Load more tracks');
  await loadMore.onclick();
  assert(fetches.at(-1).includes('cursor=after-100'));
  assert.strictEqual(fetches.at(-1), '/api/tracks/summary?limit=100&order=title&cursor=after-100');
  const tbody = tracks.children[0].children[2];
  assert.deepStrictEqual(tbody.children.map(row => row.dataset.title), ['Title 00000','Title 00100','Title 00101']);
  assert.strictEqual(tbody.children[1].className, 'current');
  assert.strictEqual(tbody.children[1].children[0].children[0].getAttribute('aria-current'), 'true');
  assert(tracks.innerText.includes('Showing 3 of 102'));
  assert(!tracks.children.some(child => child.tagName === 'NAV'), 'load more navigation disappears at end');
})().catch(error=>{console.error(error); process.exit(1);});
"""
        for app in (APP_JS, REPO_ROOT / 'music_explorer/frameworks/explorer/assets/app.js'):
            with self.subTest(app=app):
                subprocess.run(['node', '-e', script, str(app)], check=True, cwd=REPO_ROOT)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for track pagination race tests')
    def test_summary_search_resets_cursor_and_stale_next_page_does_not_mix_results(self):
        script = r"""
const assert = require('assert');
const app = require(process.argv[1]);
function deferred(){let resolve; const promise = new Promise(r => resolve = r); return {promise, resolve};}
function makeElement(tag){
  return {tagName:tag.toUpperCase(), children:[], attributes:{}, dataset:{}, className:'', value:'', textContent:'', onclick:null, oninput:null, hidden:false, disabled:false,
    append(...nodes){this.children.push(...nodes);}, replaceChildren(...nodes){this.children=[...nodes]; this.textContent='';},
    setAttribute(name,value){this.attributes[name]=String(value);}, getAttribute(name){return this.attributes[name] || null;}, removeAttribute(name){delete this.attributes[name];},
    get innerText(){return [this.textContent, ...this.children.map(c=>c.innerText || c.textContent || '')].filter(Boolean).join(' ');}
  };
}
const tracks = makeElement('div');
const search = makeElement('input');
const elements = {tracks, 'track-search': search};
global.document = {createElement: makeElement, getElementById(id){return elements[id] || null;}, querySelectorAll(){return [];}};
let next = deferred();
let fetches = [];
global.fetch = async path => {
  fetches.push(String(path));
  const text = String(path);
  if (text.includes('cursor=after-100')) return next.promise;
  if (text.includes('query=needle')) return {ok:true, json:async()=>({tracks:[{handle:'needle', title:'Needle Song', artist:'Finder'}], metadata:{track_count:1}, next_cursor:null})};
  return {ok:true, json:async()=>({tracks:[{handle:'first', title:'Alpha', artist:'Artist'}], metadata:{track_count:101}, next_cursor:'after-100'})};
};
(async()=>{
  await app.loadTrackSummaryPage('');
  const loadMore = tracks.children.find(child => child.tagName === 'NAV').children[0];
  const staleNext = loadMore.onclick();
  await Promise.resolve();
  await app.loadTrackSummaryPage('needle');
  next.resolve({ok:true, json:async()=>({tracks:[{handle:'stale', title:'Stale Old Page', artist:'Wrong'}], metadata:{track_count:101}, next_cursor:null})});
  await staleNext;
  const tbody = tracks.children[0].children[2];
  assert.deepStrictEqual(tbody.children.map(row => row.dataset.title), ['Needle Song']);
  assert(fetches.includes('/api/tracks/summary?limit=100&order=title&query=needle'));
  assert(!fetches.find(url => url.includes('query=needle') && url.includes('cursor=')), 'new search must reset cursor');
  assert(!tracks.innerText.includes('Stale Old Page'));
  assert(tracks.innerText.includes('Showing 1 of 1'));
})().catch(error=>{console.error(error); process.exit(1);});
"""
        for app in (APP_JS, REPO_ROOT / 'music_explorer/frameworks/explorer/assets/app.js'):
            with self.subTest(app=app):
                subprocess.run(['node', '-e', script, str(app)], check=True, cwd=REPO_ROOT)

    def test_static_html_copy_matches_manual_graph_loading_in_both_mirrored_assets(self):
        for package in ('music_analyzer', 'music_explorer'):
            with self.subTest(package=package):
                html = (REPO_ROOT / package / 'frameworks/explorer/assets/index.html').read_text(encoding='utf-8')
                self.assertNotIn('initial graph shows the whole library', html)
                self.assertIn('Use Load graph to render the 3D library graph manually', html)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for metadata DOM tests')
    def test_metadata_is_flat_deduplicated_and_escaped(self):
        script = r"""
const assert=require('assert'), app=require(process.argv[1]);
global.document={createElement:tag=>({tag,textContent:'',children:[],append(...children){this.children.push(...children)}})};
const metadata=app.renderTrackMetadata({common:[['title','Song'],['album artist','Band']],tags:[['TITLE',['Other']],['ALBUM_ARTIST',['Other Band']],['comment',['<script>']],['genre',['Rock']],['genre',['Jazz']],['TRACKNUMBER',['4']],['TPE2',['Other Band']]],warnings:['diagnostic warning']});
assert.deepStrictEqual(metadata.children.map(n=>n.textContent), ['Title: Song','Album artist: Band','Comment: <script>','Genre: Rock','Track number: 4']);
assert(!metadata.children.some(n=>n.tag==='details' || n.tag==='h4'));
assert.strictEqual(app.renderTrackMetadata({}).children[0].textContent,'No embedded textual metadata found');
"""
        for app in (APP_JS, REPO_ROOT / 'music_explorer/frameworks/explorer/assets/app.js'):
            with self.subTest(app=app):
                subprocess.run(['node', '-e', script, str(app)], check=True, cwd=REPO_ROOT)

    def test_detail_panel_source_removes_diagnostics_and_graph_key_from_current_track(self):
        source = APP_JS.read_text(encoding='utf-8')
        self.assertNotIn('function graphStatusText', source)
        self.assertNotIn('function graphStatusParagraph', source)
        self.assertIn('Current Track', source)
        detail_source = source[source.index('function renderDetail'):source.index('function renderTrackMetadata')]
        self.assertNotIn('Display label:', detail_source)
        self.assertNotIn('Stable identifier:', detail_source)
        self.assertNotIn('Status:', detail_source)
        self.assertNotIn('Locations:', detail_source)
        self.assertNotIn('Graph key / status', detail_source)
        self.assertNotIn('Graph key and status are shown in Current / graph notes.', source)
        self.assertIn('renderDetail', source[source.index('module.exports'):])
        self.assertIn('renderInitialDetail', source[source.index('module.exports'):])

    @unittest.skipUnless(shutil.which('node'), 'Node is required for detail panel behavior tests')
    def test_detail_panel_omits_current_track_diagnostics_and_standalone_graph_key(self):
        script = r"""
const assert = require('assert');
const app = require(process.argv[1]);
function makeElement(tag){
  return {tagName: tag.toUpperCase(), children: [], attributes: {}, dataset: {}, className: '', textContent: '',
    append(...nodes){this.children.push(...nodes);},
    replaceChildren(...nodes){this.children = [...nodes]; this.textContent = '';},
    setAttribute(name, value){this.attributes[name] = String(value);},
    get innerText(){return [this.textContent, ...this.children.map(c => c.innerText || c.textContent || '')].filter(Boolean).join('\n');}
  };
}
const elements = {detail: makeElement('div'), 'graph-info': makeElement('p')};
global.document = {getElementById: id => elements[id] || null, createElement: makeElement};
const graphModel = app.buildMoodGraphModel({selected_mood:'relaxing', positioned:[
  {track_id:'track-1', display_label:'Alpha.flac', x:{raw:-2,normalized:0,scale:'native'}, y:{raw:10,normalized:0,scale:'native'}, z:{raw:120,normalized:6,label:'BPM',scale:'raw'}, mood_score:{label:'relaxing',raw:0.85}, bpm:120, genres:[['rock',0.9]], genre_threshold:0.5, reasons:[]},
  {track_id:'track-2', display_label:'Beta.flac', x:{raw:3,normalized:1,scale:'native'}, y:{raw:30,normalized:1,scale:'native'}, z:{raw:140,normalized:7,label:'BPM',scale:'raw'}, mood_score:{label:'relaxing',raw:0.15}, bpm:140, genres:[['jazz',0.9]], genre_threshold:0.5, reasons:[]}
], edges:[{a:'track-1', b:'track-2', score:0.5}], unpositioned:[{track_id:'missing', display_label:'Missing', reasons:['no mood']}], available_moods:['relaxing']});
app.setGraphModelForTesting(graphModel);
const visible = app.applyMoodGraphFilters(graphModel, {bpmMin:130, genres:['jazz']});
app.setVisibleGraphForTesting(visible);
assert.deepStrictEqual(visible.nodes.map(n=>n.id), ['track-2']);
assert.strictEqual(visible.links.length, 0);
app.renderDetail({handle:'track-1', display_label:'Alpha.flac', latest_run_status:'completed', available_locations:1, reasons:['ready'], fields:{}});
let text = elements.detail.innerText;
assert(text.includes('Current Track'), text);
assert(!text.includes('Display label:'), text);
assert(!text.includes('Stable identifier:'), text);
assert(!text.includes('Graph key / status'), text);
assert(!text.includes('positioned tracks ·'), text);
assert(!text.includes('Color relative to this library'), text);
assert.strictEqual(elements['graph-info'].textContent, '');
app.renderInitialDetail(graphModel);
text = elements.detail.innerText;
assert.strictEqual(text, '', text);
assert(!text.includes('All-library valence / arousal / BPM graph'), text);
assert(!text.includes('Showing 1 positioned tracks and 1 unpositioned tracks'), text);
assert(!text.includes('Graph key / status'), text);
assert(!text.includes('positioned tracks ·'), text);
assert(!text.includes('Color relative to this library'), text);
assert(!text.includes('3d-force-graph is bundled locally'), text);
assert(!text.includes('fixed 20 BPM'), text);
assert(!text.includes('selected mood'), text);
assert(!text.includes('sample-relative'), text);
assert(!text.includes('Missing: no mood'), text);
"""
        for app in (APP_JS, REPO_ROOT / 'music_explorer/frameworks/explorer/assets/app.js'):
            with self.subTest(app=app):
                subprocess.run(['node', '-e', script, str(app)], check=True, cwd=REPO_ROOT)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for color behavior tests')
    def test_library_relative_color_legend_and_selection_survive_filters_and_mood_changes(self):
        script = r"""
const assert = require('assert');
const fs = require('fs'), vm = require('vm');
const app = require(process.argv[1]);
const point = (id,v,a,z) => ({track_id:id,display_label:id,x:{raw:v,normalized:v},y:{raw:a,normalized:a},z:{raw:z,normalized:z,label:'calm'}});
const positioned = [point('low',-2,10,0.1),point('high',3,30,0.8),point('middle',0.5,20,0.4)];
const model = app.buildMoodGraphModel({positioned,selected_mood:'calm'});
assert.deepStrictEqual(model.colorRanges, {valence:[-2,3],arousal:[10,30]});
assert.strictEqual(app.displayNumber(0.05),'0.1');
assert.strictEqual(app.displayNumber(-0.05),'-0.1');
assert.strictEqual(app.displayNumber(128),'128.0');
assert.strictEqual(app.displayNumber(Infinity),'Infinity');
const raw = {nodes:[{id:'one',label:'Track',moodScore:{label:'calm',raw:0.151},axis:{x:{raw:-2.46,scale:'native'},y:{raw:3.35,scale:'native'},z:{raw:128.05,label:'BPM',scale:'raw'}}}]};
const strip = app.buildMoodStrip(raw,'one');
assert.strictEqual(strip[0].position,0.151);
assert.strictEqual(strip[0].score,0.151);
assert(strip[0].description.includes('0.2 / 1'));
assert(app.nodeLabel(raw.nodes[0]).includes('valence -2.5 (native)'));
assert(app.nodeLabel(raw.nodes[0]).includes('arousal 3.4 (native)'));
assert(app.nodeLabel(raw.nodes[0]).includes('BPM 128.1 (raw)'));
assert(app.nodeLabel(raw.nodes[0]).includes('calm 0.2 / 1'));
assert.strictEqual(raw.nodes[0].moodScore.raw,0.151);
assert.deepStrictEqual(app.graphAxisSpec([{x:72,y:108,z:4320},{x:252,y:180,z:4608}]).map(a=>a.references),[['0.2','0.7'],['0.3','0.5'],['120.0','128.0']]);

assert.strictEqual(app.graphColorLegend({colorRanges:{valence:[-2.46,3.35],arousal:[10.01,30.08]}}).includes('-2.5 to 3.4'),true);
assert.strictEqual(model.nodes[0].color, app.moodNodeColor(0,0));
assert.strictEqual(model.nodes[1].color, app.moodNodeColor(1,1));
assert.strictEqual(model.nodes[2].color, app.moodNodeColor(0.5,0.5));
assert.notStrictEqual(model.nodes[0].color,model.nodes[1].color);
assert.notStrictEqual(app.moodNodeColor(0,0),app.moodNodeColor(0,1));
assert.notStrictEqual(app.moodNodeColor(0,1),app.moodNodeColor(1,1));
const filtered = app.applyMoodGraphFilters(model,{bpmMin:0});
assert.deepStrictEqual(filtered.nodes,[]);
model.nodes[0].bpm=120; model.nodes[1].bpm=140;
assert.strictEqual(app.applyMoodGraphFilters(model,{bpmMin:130}).nodes[0].color,model.nodes[1].color);
assert.deepStrictEqual(app.applyMoodGraphFilters(model,{}).nodes.map(n=>n.color),model.nodes.map(n=>n.color));
const other = app.buildMoodGraphModel({positioned:positioned.map(n=>({...n,z:{...n.z,raw:0.9,normalized:0.9,label:'heavy'}})),selected_mood:'heavy'});
assert.deepStrictEqual(other.nodes.map(n=>n.color),model.nodes.map(n=>n.color));
const flat = app.buildMoodGraphModel({positioned:[point('one',7,-5,0),point('two',7,-5,1)]});
assert.deepStrictEqual(flat.colorRanges,{valence:[7,7],arousal:[-5,-5]});
assert(flat.nodes.every(n=>n.color===app.moodNodeColor(0.5,0.5)));
assert(app.graphColorLegend(model).includes('relative to this library'));
assert(app.graphColorLegend(model).includes('-2.0 to 3.0'));
assert(app.graphColorLegend(model).includes('10.0 to 30.0'));
assert(app.graphColorLegend(model).includes('blue'));
assert(app.graphColorLegend(model).includes('bright'));
const context = {module:{exports:{}},console,URLSearchParams};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
assert.strictEqual(context.linkLabel({score:0.151,explanation:'related',supportedGroupCount:3}),'score 0.2; related; groups 3');
let color, size, info={textContent:''};
const graph = new Proxy({}, {get(_,key){
 if(key==='nodeColor') return callback=>{color=callback;return graph};
 if(key==='nodeVal') return callback=>{size=callback;return graph};
 if(key==='camera') return ()=>({fov:60});
 return ()=>graph;
}});
context.ForceGraph3D=()=>()=>graph;
context.document={getElementById:id=>id==='graph3d'?{clientWidth:900,clientHeight:500}:id==='graph-info'?info:null};
vm.runInContext("state.current_track_id='low'",context);
vm.runInContext('graphModel=buildMoodGraphModel('+JSON.stringify({positioned,selected_mood:'calm'})+')',context);
context.renderMap(model);
assert.strictEqual(color(model.nodes[0]),model.nodes[0].color,'selection must not replace color');
assert(size(model.nodes[0])>size(model.nodes[1]),'selection should be larger');
assert.strictEqual(info.textContent, '', 'removed graph status panel must not be updated');
vm.runInContext("selectedGraphControls={mood:'heavy',bpmMin:100,bpmMax:140,genres:['jazz']}",context);
assert.strictEqual(context.graphQueryFromControls(),'?mood=heavy','fetch full mood library before local filtering');
"""
        subprocess.run(['node', '-e', script, str(APP_JS)], check=True, cwd=REPO_ROOT)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for camera behavior tests')
    def test_graph_camera_centers_bounds_fits_viewport_and_preserves_selection_view(self):
        script = r"""
const assert = require('assert');
const app = require(process.argv[1]);
const nodes = [{id:'a',x:900,y:200,z:-80}, {id:'b',x:1500,y:600,z:120}];
const before = JSON.stringify(nodes);
const wide = app.graphCameraFrame(nodes, {width:1000,height:500}, 60);
assert.deepStrictEqual(wide.target, {x:1200,y:400,z:20});
assert.strictEqual(wide.position.x, 1200);
assert.strictEqual(wide.position.y, 400);
const narrow = app.graphCameraFrame(nodes, {width:250,height:500}, 60);
assert(narrow.position.z > wide.position.z, 'portrait viewport needs more distance');
const tightFov = app.graphCameraFrame(nodes, {width:1000,height:500}, 30);
assert(tightFov.position.z > wide.position.z);
for (const [frame, aspect] of [[wide,2], [narrow,0.5]]) {
  for (const n of nodes) {
    const depth = frame.position.z - n.z - 4;
    assert(Math.abs(n.x-frame.target.x)+4 < depth*Math.tan(Math.PI/6)*aspect);
    assert(Math.abs(n.y-frame.target.y)+4 < depth*Math.tan(Math.PI/6));
  }
}
assert.strictEqual(JSON.stringify(nodes), before, 'camera framing must not translate data');
assert.deepStrictEqual(app.graphCameraFrame([...nodes,{x:NaN,y:0,z:0}], {width:1000,height:500},60), wide);
for (const input of [[], [{x:Infinity,y:0,z:0}], [nodes[0]]]) {
  const frame = app.graphCameraFrame(input, {width:0,height:0}, NaN);
  assert(Object.values(frame.position).every(Number.isFinite));
  assert(frame.position.z > frame.target.z);
}
assert.deepStrictEqual(app.graphCameraFrame([nodes[0]], {width:500,height:500},60).target, {x:900,y:200,z:-80});
assert.deepStrictEqual(app.graphCameraFrame([], {width:500,height:500},60).target, {x:0,y:0,z:0});

const vm = require('vm'), fs = require('fs');
const context = {module:{exports:{}}, console};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
const calls = [];
const graph = new Proxy({}, {get(_, key){
  if(key==='camera') return ()=>({fov:60});
  if(key==='cameraPosition') return (...args)=>{calls.push(args); return graph;};
  return ()=>graph;
}});
context.ForceGraph3D = ()=>()=>graph;
context.document = {getElementById: id=>id==='graph3d'?{clientWidth:1000,clientHeight:500}:null};
context.renderMap({nodes,links:[],unpositioned:[]});
assert.strictEqual(calls.length,1);
assert.deepStrictEqual(JSON.parse(JSON.stringify(calls[0][1])),wide.target);
vm.runInContext("state.current_track_id='a'", context);
context.renderMap({nodes:JSON.parse(before),links:[],unpositioned:[]});
assert.strictEqual(calls.length,1,'selection/detail refresh must preserve user orbit/zoom/pan');
context.renderMap({nodes:[nodes[0]],links:[],unpositioned:[]});
assert.strictEqual(calls.length,2,'filtering to different bounds reframes');
context.renderMap({nodes:[{...nodes[0],x:950}],links:[],unpositioned:[]});
assert.strictEqual(calls.length,3,'changed layout reframes');
"""
        subprocess.run(['node', '-e', script, str(APP_JS)], check=True, cwd=REPO_ROOT)



    @unittest.skipUnless(shutil.which('node'), 'Node is required for same-layout graph updates')
    def test_same_layout_graph_update_tolerates_missing_live_nodes(self):
        script = r"""
const assert = require('assert');
const fs = require('fs'), vm = require('vm');
const context = {module:{exports:{}}, console, requestAnimationFrame(){}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
const graph = new Proxy({stored:null}, {get(target,key){
  if(key === 'graphData') return data => { if (data) target.stored = data; return data ? graph : graph; };
  if(key === 'camera') return () => ({fov:60});
  return () => graph;
}});
context.ForceGraph3D = () => () => graph;
context.document = {getElementById:id=>id==='graph3d'?{clientWidth:900,clientHeight:500,parentElement:null}:id==='graph-info'?{textContent:''}:null};
const node = {id:'a',label:'A',color:'#123',x:10,y:20,z:30,fx:10,fy:20,fz:30,axis:{x:{raw:1},y:{raw:2},z:{raw:3,label:'BPM'}},moodScore:{label:'calm',raw:0.4},genres:[]};
context.graphModel = {nodes:[node],links:[],unpositioned:[],selectedMood:'calm',colorRanges:{}};
context.renderMap({nodes:[node],links:[],unpositioned:[]});
graph.stored = undefined; // 3d-force-graph can transiently report no data for the same layout.
assert.doesNotThrow(() => context.renderMap({nodes:[{...node,moodScore:{label:'calm',raw:0.9}}],links:[],unpositioned:[]}));
""";
        subprocess.run(['node', '-e', script, str(APP_JS)], check=True, cwd=REPO_ROOT)



    @unittest.skipUnless(shutil.which('node'), 'Node is required for selection token protocol tests')
    def test_click_posts_epoch_scoped_tab_token_and_syncs_epoch_after_reset(self):
        script = r"""
const assert = require('assert');
const fs = require('fs'), vm = require('vm');
const context = {module:{exports:{}}, console, URLSearchParams, requestAnimationFrame(){}, Date, Math,
  sessionStorage:{data:{}, getItem(k){return this.data[k]||null;}, setItem(k,v){this.data[k]=v;}}
};
(async () => {
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
function response(payload){return {ok:true, json:async()=>payload};}
const bodies=[];
context.fetch = (path, options={}) => {
  if (path === '/api/current') { bodies.push(JSON.parse(options.body)); return Promise.resolve(response({current_track_id: JSON.parse(options.body).track_id, selection_epoch: bodies.length === 1 ? 7 : 8})); }
  if (path === '/api/reset') return Promise.resolve(response({current_track_id:null, selection_epoch:8}));
  if (path === '/api/tracks/a' || path === '/api/tracks/b') return Promise.resolve(response({handle:path.slice(-1), display_label:path.slice(-1).toUpperCase(), latest_run_status:'completed', available_locations:1, reasons:[], fields:{}}));
  if (String(path).startsWith('/api/candidates?')) return Promise.resolve(response({candidates:[]}));
  return Promise.resolve(response({}));
};
function canvasContext(){return {clearRect(){}, fillRect(){}, beginPath(){}, moveTo(){}, lineTo(){}, stroke(){}, arc(){}, fill(){}};}
function element(tag){return {tag, textContent:'', className:'', dataset:{}, style:{}, children:[], clientWidth:600, clientHeight:70, width:0, height:0, getContext(){return canvasContext();}, setAttribute(){}, append(...nodes){this.children.push(...nodes);}, replaceChildren(...nodes){this.children=nodes;}};}
const elements = {detail: element('section'), candidates: element('ol'), 'mood-strip': element('canvas'), 'mood-strip-picker': element('input'), 'mood-strip-value': element('output')};
context.document = {createElement: element, querySelector(){return null;}, querySelectorAll(){return [];}, getElementById(id){return elements[id] || element(id);}};
context.refresh = () => Promise.resolve();
vm.runInContext("state={current_track_id:null,selection_epoch:7}; selectionEpoch=7; graphModel={nodes:[],links:[],unpositioned:[],selectedMood:'',colorRanges:{}}; visibleGraph={nodes:[],links:[],unpositioned:[]}; refresh = globalThis.refresh;", context);
await context.setCurrent('a');
assert.strictEqual(bodies[0].selection_epoch, 7);
assert.strictEqual(bodies[0].selection_token, 1);
assert(/^tab-/.test(bodies[0].selection_client_id), 'tab-scoped client id is sent');
await context.applyHistorySelection('/api/reset');
await context.setCurrent('b');
assert.strictEqual(bodies[1].selection_epoch, 8, 'reset response epoch is used by next click');
assert.strictEqual(bodies[1].selection_token, 2, 'same tab keeps monotonically increasing tokens across reload-safe session state');
assert.strictEqual(bodies[1].selection_client_id, bodies[0].selection_client_id, 'same tab keeps stable client id');
})().catch(error => { console.error(error); process.exit(1); });
""";
        subprocess.run(['node', '-e', script, str(APP_JS)], check=True, cwd=REPO_ROOT)


    @unittest.skipUnless(shutil.which('node'), 'Node is required for selection rejection behavior tests')
    def test_rejected_selection_snapshot_does_not_override_optimistic_click(self):
        script = r"""
const assert = require('assert');
const fs = require('fs'), vm = require('vm');
const context = {module:{exports:{}}, console, URLSearchParams, requestAnimationFrame(){}, Date, Math,
  sessionStorage:{data:{}, getItem(k){return this.data[k]||null;}, setItem(k,v){this.data[k]=v;}}
};
(async () => {
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
function response(payload){return {ok:true, json:async()=>payload};}
const fetches=[];
let resolveCurrent;
const currentResponse = new Promise(resolve => { resolveCurrent = resolve; });
context.fetch = (path, options={}) => {
  fetches.push(String(path));
  if (path === '/api/current') return currentResponse.then(() => response({current_track_id:'server-current', selection_epoch:0, selection_accepted:false}));
  if (path === '/api/tracks/client-click') return Promise.resolve(response({handle:'client-click', display_label:'Client Click', latest_run_status:'completed', available_locations:1, reasons:[], fields:{}}));
  if (path === '/api/tracks/server-current') return Promise.resolve(response({handle:'server-current', display_label:'Server Current', latest_run_status:'completed', available_locations:1, reasons:[], fields:{}}));
  if (String(path).startsWith('/api/candidates?')) return Promise.resolve(response({candidates:[]}));
  throw new Error('unexpected fetch '+path);
};
function canvasContext(){return {clearRect(){}, fillRect(){}, beginPath(){}, moveTo(){}, lineTo(){}, stroke(){}, arc(){}, fill(){}};}
function element(tag){return {tag, textContent:'', className:'', dataset:{}, style:{}, children:[], clientWidth:600, clientHeight:70, width:0, height:0, getContext(){return canvasContext();}, setAttribute(){}, append(...nodes){this.children.push(...nodes);}, replaceChildren(...nodes){this.children=nodes;}};}
const detail = element('section');
const elements = {detail, candidates: element('ol'), 'mood-strip': element('canvas'), 'mood-strip-picker': element('input'), 'mood-strip-value': element('output')};
const rows = ['client-click','server-current'].map(id => ({dataset:{trackId:id}, className:''}));
context.document = {createElement: element, querySelector(){return null;}, querySelectorAll(selector){assert.strictEqual(selector, '#tracks tr[data-track-id]'); return rows;}, getElementById(id){return elements[id] || element(id);}};
vm.runInContext("state={current_track_id:'server-current'}; selectionEpoch=0; graphModel={nodes:[{id:'client-click',moodScore:null},{id:'server-current',moodScore:null}],links:[],unpositioned:[],selectedMood:'',colorRanges:{}}; visibleGraph={nodes:graphModel.nodes,links:[],unpositioned:[]};", context);
const click = context.setCurrent('client-click');
await Promise.resolve();
assert.strictEqual(vm.runInContext('state.current_track_id', context), 'client-click', 'selection is optimistic before the server responds');
resolveCurrent();
await click;
assert.strictEqual(vm.runInContext('state.current_track_id', context), 'server-current', 'rejected/stale server snapshot must restore the accepted server selection');
assert.deepStrictEqual(rows.map(r => r.className), ['', 'current']);
assert(fetches.includes('/api/tracks/server-current'), 'detail fetch follows the accepted server snapshot after rejection');
assert(detail.children.some(child => child.textContent.includes('Current Track')));
})().catch(error => { console.error(error); process.exit(1); });
""";
        subprocess.run(['node', '-e', script, str(APP_JS)], check=True, cwd=REPO_ROOT)


    @unittest.skipUnless(shutil.which('node'), 'Node is required for selection rejection refresh tests')
    def test_refresh_after_rejected_selection_uses_authoritative_server_selection(self):
        script = r"""
const assert = require('assert');
const fs = require('fs'), vm = require('vm');
const context = {module:{exports:{}}, console, URLSearchParams, requestAnimationFrame(cb){Promise.resolve().then(cb);}, Date, Math,
  sessionStorage:{data:{}, getItem(k){return this.data[k]||null;}, setItem(k,v){this.data[k]=v;}}
};
(async () => {
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
function response(payload){return {ok:true, json:async()=>payload};}
function point(id){return {track_id:id, display_label:id.toUpperCase(), title:id, artist:'Artist', x:{raw:0, normalized:0.5, scale:'native', label:'valence'}, y:{raw:0, normalized:0.5, scale:'native', label:'arousal'}, z:{raw:120, normalized:0.5, scale:'raw', label:'BPM'}, mood_score:{label:'calm', raw:0.5, normalized:0.5}, genres:[]};}
const fetches = [];
context.fetch = (path, options={}) => {
  fetches.push(String(path));
  if (path === '/api/current') return Promise.resolve(response({current_track_id:'server-current', selection_epoch:2, selection_accepted:false}));
  if (path === '/api/state') return Promise.resolve(response({current_track_id:'server-current', selection_epoch:2}));
  if (path === '/api/tracks/summary?limit=100&order=title') return Promise.resolve(response({tracks:[{handle:'client-click', display_label:'Client Click'},{handle:'server-current', display_label:'Server Current'}]}));
  if (path === '/api/mood-axis-graph') return Promise.resolve(response({positioned:[point('client-click'), point('server-current')], edges:[], selected_mood:'calm', available_moods:['calm']}));
  if (path === '/api/tracks/client-click') return Promise.resolve(response({handle:'client-click', display_label:'Client Click', latest_run_status:'completed', available_locations:1, reasons:[], fields:{}}));
  if (path === '/api/tracks/server-current') return Promise.resolve(response({handle:'server-current', display_label:'Server Current', latest_run_status:'completed', available_locations:1, reasons:[], fields:{}}));
  if (String(path).startsWith('/api/candidates?')) {
    const current = String(path).includes('current=server-current') ? 'server-candidate' : 'client-candidate';
    return Promise.resolve(response({candidates:[{track_id:current, tier:'strong', score:0.8}]}));
  }
  return Promise.reject(new Error('unexpected fetch '+path));
};
function canvasContext(){return {clearRect(){}, fillRect(){}, beginPath(){}, moveTo(){}, lineTo(){}, stroke(){}, arc(){}, fill(){}};}
function element(tag){return {tag, id:'', textContent:'', className:'', dataset:{}, style:{}, children:[], clientWidth:800, clientHeight:600, value:'', options:[], getContext(){return canvasContext();}, setAttribute(){}, append(...nodes){this.children.push(...nodes);}, replaceChildren(...nodes){this.children = nodes;}, replaceWith(){}};}
const elements = {tracks: element('div'), detail: element('section'), candidates: element('ol'), 'mood-strip': element('canvas'), 'mood-strip-picker': element('input'), 'mood-strip-value': element('output'), 'selected-mood': element('select'), 'genre-filter': element('select'), 'graph-info': element('p')};
context.document = {createElement: element, createTextNode(value){return {textContent:String(value)};}, querySelector(){return null;}, querySelectorAll(selector){assert.strictEqual(selector, '#tracks tr[data-track-id]'); return elements.tracks.children.length ? elements.tracks.children[0].children[2].children : [];}, getElementById(id){return elements[id] || null;}};
vm.runInContext("state={current_track_id:'server-current'}; selectionEpoch=1; graphModel={nodes:[{id:'client-click',moodScore:null},{id:'server-current',moodScore:null}],links:[],unpositioned:[],selectedMood:'',colorRanges:{}}; visibleGraph={nodes:graphModel.nodes,links:[],unpositioned:[]};", context);
await context.setCurrent('client-click');
assert.strictEqual(vm.runInContext('state.current_track_id', context), 'server-current', 'rejected POST restores authoritative server selection');
await context.refresh();
assert.strictEqual(vm.runInContext('state.current_track_id', context), 'server-current', 'refresh after rejection must not overlay the rejected click intent');
assert.deepStrictEqual(elements.tracks.children[0].children[2].children.map(row => row.className), ['', 'current']);
assert(elements.detail.children.some(child => child.textContent.includes('Current Track')), 'detail follows authoritative server selection after refresh');
assert(!fetches.some(path => path.startsWith('/api/candidates')), 'refresh does not request removed candidate list');
assert(fetches.includes('/api/current') && fetches.includes('/api/state'));
})().catch(error => { console.error(error); process.exit(1); });
"""
        subprocess.run(['node', '-e', script, str(APP_JS)], check=True, cwd=REPO_ROOT)


    @unittest.skipUnless(shutil.which('node'), 'Node is required for selection detail regression tests')
    def test_selected_detail_does_not_depend_on_removed_candidates_endpoint(self):
        script = r"""
const assert = require('assert');
const fs = require('fs'), vm = require('vm');
(async () => {
const context = {module:{exports:{}}, console, URLSearchParams};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
function response(payload){return {ok:true, json:async()=>payload};}
const fetches = [];
context.fetch = path => {
  fetches.push(String(path));
  if (path === '/api/tracks/a') return Promise.resolve(response({handle:'a', display_label:'Track A', latest_run_status:'completed', available_locations:1, reasons:[], fields:{}}));
  if (String(path).startsWith('/api/candidates')) return Promise.reject(new Error('candidates unavailable'));
  throw new Error('unexpected fetch '+path);
};
function element(tag){return {tag, textContent:'', className:'', dataset:{}, style:{}, children:[], setAttribute(){}, append(...nodes){this.children.push(...nodes);}, replaceChildren(...nodes){this.children=nodes;}};}
const detail = element('section');
context.document = {createElement: element, querySelectorAll(){return [];}, getElementById(id){return id==='detail'?detail:null;}};
vm.runInContext("state={current_track_id:'a'}; graphModel={nodes:[],links:[],unpositioned:[],selectedMood:'',colorRanges:{}}; visibleGraph={nodes:[],links:[],unpositioned:[]};", context);
await context.refreshSelectionDependent(0);
assert(fetches.includes('/api/tracks/a'), 'selected detail is fetched');
assert(!fetches.some(path => path.startsWith('/api/candidates')), 'removed list endpoint is not requested');
assert(detail.children.some(child => child.textContent.includes('Current Track')), 'detail renders even when candidates are unavailable');
})().catch(error => {console.error(error); process.exit(1);});
"""
        for app in (APP_JS, REPO_ROOT / 'music_explorer/frameworks/explorer/assets/app.js'):
            with self.subTest(app=app):
                subprocess.run(['node', '-e', script, str(app)], check=True, cwd=REPO_ROOT)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for selection behavior tests')
    def test_selection_only_fetches_detail_and_keeps_graph_data(self):
        script = r"""
const assert = require('assert');
const fs = require('fs'), vm = require('vm');
const context = {module:{exports:{}}, console, URLSearchParams};
(async () => {
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
function deferred(){let resolve; const promise = new Promise(r => {resolve = r;}); return {promise, resolve};}
function response(payload){return {ok:true, json:async()=>payload};}
const detailA = deferred();
const fetches = [];
context.fetch = (path, options={}) => {
  fetches.push(String(path));
  if (path === '/api/current') {
    const body = JSON.parse(options.body);
    return Promise.resolve(response({current_track_id: body.track_id}));
  }
  if (path === '/api/tracks/a') return detailA.promise.then(payload => response(payload));
  if (path === '/api/tracks/b') return Promise.resolve(response({handle:'b', display_label:'Bee', latest_run_status:'completed', available_locations:1, reasons:[], fields:{}}));
  throw new Error('unexpected fetch '+path);
};
function element(tag){return {tag, textContent:'', className:'', dataset:{}, style:{}, children:[], setAttribute(){}, append(...nodes){this.children.push(...nodes);}, replaceChildren(...nodes){this.children = nodes;}};}
const detail = element('section'), candidates = element('ol');
const rows = ['a','b'].map(id => ({dataset:{trackId:id}, className:''}));
context.document = {createElement: element, querySelector(){return null;}, querySelectorAll(selector){assert.strictEqual(selector, '#tracks tr[data-track-id]'); return rows;}, getElementById(id){return id === 'detail' ? detail : id === 'candidates' ? candidates : null;}};
const graphCalls = [];
const graph = {nodeVal(fn){this.value = fn; return this;}, refresh(){this.refreshed = (this.refreshed || 0) + 1; return this;}, graphData(data){graphCalls.push(data); return {nodes:[]};}};
context.graph = graph;
vm.runInContext("state={current_track_id:null}; graphModel={nodes:[{id:'a',label:'A',moodScore:null},{id:'b',label:'B',moodScore:null}],links:[],unpositioned:[],selectedMood:'calm',colorRanges:{}}; visibleGraph={nodes:graphModel.nodes,links:[],unpositioned:[]}; forceGraph=graph;", context);
const first = context.setCurrent('a');
for(let i=0;i<8 && !fetches.includes('/api/tracks/a');i++) await Promise.resolve();
assert(fetches.includes('/api/tracks/a'), 'first detail request is in flight');
const second = context.setCurrent('b');
await second;
detailA.resolve({handle:'a', display_label:'A stale', latest_run_status:'completed', available_locations:1, reasons:[], fields:{}});
await first;
assert.deepStrictEqual(fetches.filter(u => u === '/api/tracks/summary?limit=100&order=title' || u.startsWith('/api/mood-axis-graph')), []);
assert(fetches.includes('/api/current'));
assert(fetches.includes('/api/tracks/a'));
assert(fetches.includes('/api/tracks/b'));
assert.strictEqual(graphCalls.length, 0, 'selection-only changes must not replace forceGraph.graphData');
assert.strictEqual(graph.value({id:'b'}), 4);
assert.strictEqual(graph.value({id:'a'}), 1);
assert.deepStrictEqual(rows.map(r => r.className), ['', 'current']);
assert(detail.children.some(child => child.textContent.includes('Current Track')), 'stale first detail must not overwrite latest selection');
assert(!fetches.some(path => path.startsWith('/api/candidates')), 'selection does not request removed candidate list');
assert(graph.refreshed >= 2, 'selected node styling is refreshed locally');
})().catch(error => { console.error(error); process.exit(1); });
""";
        subprocess.run(['node', '-e', script, str(APP_JS)], check=True, cwd=REPO_ROOT)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for refresh race tests')
    def test_stale_full_refresh_does_not_overwrite_newer_selection_refresh(self):
        script = r"""
const assert = require('assert');
const fs = require('fs'), vm = require('vm');
const frames = [];
const context = {module:{exports:{}}, console, URLSearchParams, requestAnimationFrame(cb){frames.push(cb);}};
(async () => {
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
function runNextFrame(){assert(frames.length, 'expected an animation frame callback'); frames.shift()();}
async function waitForFetch(path){for(let i=0;i<20 && !fetches.includes(path);i++) await Promise.resolve(); assert(fetches.includes(path), `expected fetch ${path}`);}
function deferred(){let resolve; const promise = new Promise(r => {resolve = r;}); return {promise, resolve};}
function response(payload){return {ok:true, json:async()=>payload};}
function point(id){return {id, label:id.toUpperCase(), title:id, artist:'Artist', x:{raw:0, normalized:0.5, scale:'native', label:'valence'}, y:{raw:0, normalized:0.5, scale:'native', label:'arousal'}, z:{raw:120, normalized:0.5, scale:'raw', label:'BPM'}, mood_score:{label:'calm', raw:0.5, normalized:0.5}, genres:[]};}
const refreshState = deferred(), refreshList = deferred();
const detailA = deferred();
const fetches = [];
context.fetch = (path, options={}) => {
  fetches.push(String(path));
  if (path === '/api/state') return refreshState.promise.then(payload => response(payload));
  if (path === '/api/tracks/summary?limit=100&order=title') return refreshList.promise.then(payload => response(payload));
  if (path === '/api/current') return Promise.resolve(response({current_track_id:'b'}));
  if (path === '/api/tracks/b') return Promise.resolve(response({handle:'b', display_label:'Bee', latest_run_status:'completed', available_locations:1, reasons:[], fields:{}}));
  if (path === '/api/tracks/a') return detailA.promise.then(payload => response(payload));
  throw new Error('unexpected fetch '+path);
};
function element(tag){return {tag, id:'', textContent:'', className:'', dataset:{}, style:{}, children:[], clientWidth:800, clientHeight:600, getContext(){return {clearRect(){}, fillRect(){}, beginPath(){}, moveTo(){}, lineTo(){}, stroke(){}, arc(){}, fill(){}};}, setAttribute(){}, append(...nodes){this.children.push(...nodes);}, replaceChildren(...nodes){this.children = nodes;}, replaceWith(){}};}
const elements = {tracks: element('div'), detail: element('section'), candidates: element('ol'), 'mood-strip': element('canvas'), 'mood-strip-picker': element('input'), 'mood-strip-value': element('output'), 'selected-mood': element('select'), 'genre-filter': element('select'), 'graph-info': element('p')};
context.document = {createElement: element, createTextNode(value){return {textContent:String(value)};}, querySelector(){return null;}, querySelectorAll(selector){assert.strictEqual(selector, '#tracks tr[data-track-id]'); return elements.tracks.children.length ? elements.tracks.children[0].children[2].children : [];}, getElementById(id){return elements[id] || null;}};
const rendered = [];
context.renderMap = data => rendered.push(data.nodes.map(n => n.id));
vm.runInContext('renderMap = globalThis.renderMap', context);
const stale = context.refresh();
assert.deepStrictEqual(fetches, [], 'full refresh waits for the initial paint frame before fetching');
runNextFrame();
await waitForFetch('/api/state');
refreshState.resolve({current_track_id:'a'});
await waitForFetch('/api/tracks/summary?limit=100&order=title');
assert(fetches.includes('/api/tracks/summary?limit=100&order=title'), 'stale refresh reached the list request');
const latest = context.setCurrent('b');
await latest;
refreshList.resolve({tracks:[{handle:'a', display_label:'Aye'}]});
detailA.resolve({handle:'a', display_label:'A stale', latest_run_status:'completed', available_locations:1, reasons:[], fields:{}});
await stale;
assert.strictEqual(vm.runInContext('state.current_track_id', context), 'b', 'stale refresh state must not overwrite newer selection state');
assert.deepStrictEqual(elements.tracks.children.map(row => row.dataset.trackId), [], 'stale refresh must not render stale track list');
assert.deepStrictEqual(rendered, [], 'stale refresh must not render stale graph data');
assert(elements.detail.children.some(child => child.textContent.includes('Current Track')), 'stale refresh detail must not overwrite latest selection detail');
assert(!fetches.some(path => path.startsWith('/api/candidates')), 'selection does not request removed candidate list');
assert(fetches.includes('/api/tracks/summary?limit=100&order=title'));
})().catch(error => { console.error(error); process.exit(1); });
""";
        subprocess.run(['node', '-e', script, str(APP_JS)], check=True, cwd=REPO_ROOT)


    @unittest.skipUnless(shutil.which('node'), 'Node is required for same-selection detail race tests')
    def test_older_selection_detail_cannot_overwrite_newer_full_refresh_for_same_selection(self):
        script = r"""
const assert = require('assert');
const fs = require('fs'), vm = require('vm');
const context = {module:{exports:{}}, console, URLSearchParams, requestAnimationFrame(cb){Promise.resolve().then(cb);}};
(async () => {
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
function deferred(){let resolve; const promise = new Promise(r => {resolve = r;}); return {promise, resolve};}
function response(payload){return {ok:true, json:async()=>payload};}
function point(id){return {track_id:id, display_label:id.toUpperCase(), title:id, artist:'Artist', x:{raw:0, normalized:0.5, scale:'native', label:'valence'}, y:{raw:0, normalized:0.5, scale:'native', label:'arousal'}, z:{raw:120, normalized:0.5, scale:'raw', label:'BPM'}, mood_score:{label:'calm', raw:0.5, normalized:0.5}, genres:[]};}
const olderDetail = deferred();
let trackDetailRequests = 0;
const fetches = [];
context.fetch = (path, options={}) => {
  fetches.push(String(path));
  if (path === '/api/current') return Promise.resolve(response({current_track_id:'a'}));
  if (path === '/api/state') return Promise.resolve(response({current_track_id:'a'}));
  if (path === '/api/tracks/summary?limit=100&order=title') return Promise.resolve(response({tracks:[{handle:'a', display_label:'Aye'}]}));
  if (path === '/api/mood-axis-graph') return Promise.resolve(response({positioned:[point('a')], edges:[], selected_mood:'calm', available_moods:['calm']}));
  if (path === '/api/tracks/a') {
    trackDetailRequests += 1;
    return trackDetailRequests === 1
      ? olderDetail.promise.then(payload => response(payload))
      : Promise.resolve(response({handle:'a', display_label:'Fresh detail', latest_run_status:'completed', available_locations:1, reasons:[], fields:{}}));
  }
  return Promise.reject(new Error('unexpected fetch '+path));
};
function element(tag){return {tag, id:'', textContent:'', className:'', dataset:{}, style:{}, children:[], clientWidth:800, clientHeight:600, value:'', options:[], getContext(){return {clearRect(){}, fillRect(){}, beginPath(){}, moveTo(){}, lineTo(){}, stroke(){}, arc(){}, fill(){}};}, setAttribute(){}, append(...nodes){this.children.push(...nodes);}, replaceChildren(...nodes){this.children = nodes;}, replaceWith(){}};}
const elements = {tracks: element('div'), detail: element('section'), candidates: element('ol'), 'mood-strip': element('canvas'), 'mood-strip-picker': element('input'), 'mood-strip-value': element('output'), 'selected-mood': element('select'), 'genre-filter': element('select'), 'graph-info': element('p')};
context.document = {createElement: element, createTextNode(value){return {textContent:String(value)};}, querySelector(){return null;}, querySelectorAll(selector){assert.strictEqual(selector, '#tracks tr[data-track-id]'); return elements.tracks.children.length ? elements.tracks.children[0].children[2].children : [];}, getElementById(id){return elements[id] || null;}};
vm.runInContext("state={current_track_id:'a'}; selectionEpoch=1; graphModel={nodes:[{id:'a',moodScore:null}],links:[],unpositioned:[],selectedMood:'',colorRanges:{}}; visibleGraph={nodes:graphModel.nodes,links:[],unpositioned:[]};", context);
const olderRefresh = context.refresh();
await Promise.resolve();
assert.strictEqual(vm.runInContext('state.current_track_id', context), 'a', 'older refresh observed the selected track while detail is pending');
const newerRefresh = context.refresh();
await newerRefresh;
assert(elements.detail.children.some(child => child.textContent.includes('Fresh detail')), 'newer full refresh renders current detail first');
olderDetail.resolve({handle:'a', display_label:'Stale delayed detail', latest_run_status:'completed', available_locations:1, reasons:[], fields:{}});
await olderRefresh;
assert.strictEqual(vm.runInContext('state.current_track_id', context), 'a');
assert(elements.detail.children.some(child => child.textContent.includes('Fresh detail')), 'older delayed detail for same selected id must not overwrite newer refresh detail');
assert.strictEqual(trackDetailRequests, 2);
assert(!fetches.some(path => path.startsWith('/api/candidates')), 'refreshes do not request removed candidate list');
assert.strictEqual(fetches.filter(path => path === '/api/state').length, 2);
assert(!fetches.includes('/api/current'), 'non-selection refreshes reproduce the same-selected-id detail race without a click');
})().catch(error => { console.error(error); process.exit(1); });
""";
        subprocess.run(['node', '-e', script, str(APP_JS)], check=True, cwd=REPO_ROOT)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for click/refresh race tests')
    def test_refresh_after_click_before_post_resolves_preserves_latest_selection_intent(self):
        script = r"""
const assert = require('assert');
const fs = require('fs'), vm = require('vm');
const context = {module:{exports:{}}, console, URLSearchParams, requestAnimationFrame(cb){Promise.resolve().then(cb);}};
(async () => {
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
function deferred(){let resolve; const promise = new Promise(r => {resolve = r;}); return {promise, resolve};}
function response(payload){return {ok:true, json:async()=>payload};}
function point(id){return {track_id:id, display_label:id.toUpperCase(), title:id, artist:'Artist', x:{raw:0, normalized:0.5, scale:'native', label:'valence'}, y:{raw:0, normalized:0.5, scale:'native', label:'arousal'}, z:{raw:120, normalized:0.5, scale:'raw', label:'BPM'}, mood_score:{label:'calm', raw:0.5, normalized:0.5}, genres:[]};}
const postCurrent = deferred();
const fetches = [];
context.fetch = (path, options={}) => {
  fetches.push(String(path));
  if (path === '/api/current') return postCurrent.promise.then(() => response({current_track_id:'b'}));
  if (path === '/api/state') return Promise.resolve(response({current_track_id:'a'}));
  if (path === '/api/tracks/summary?limit=100&order=title') return Promise.resolve(response({tracks:[{handle:'a', display_label:'Aye'},{handle:'b', display_label:'Bee'}]}));
  if (path === '/api/mood-axis-graph') return Promise.resolve(response({positioned:[point('a'), point('b')], edges:[], selected_mood:'calm', available_moods:['calm']}));
  if (path === '/api/tracks/b') return Promise.resolve(response({handle:'b', display_label:'Bee', latest_run_status:'completed', available_locations:1, reasons:[], fields:{}}));
  if (path === '/api/tracks/a') return Promise.resolve(response({handle:'a', display_label:'A stale', latest_run_status:'completed', available_locations:1, reasons:[], fields:{}}));
  if (String(path).startsWith('/api/candidates?current=')) {
    const current = String(path).includes('current=b') ? 'cand-b' : 'cand-a';
    return Promise.resolve(response({candidates:[{track_id:current, tier:'strong', score:0.8}]}));
  }
  return Promise.reject(new Error('unexpected fetch '+path));
};
function element(tag){return {tag, id:'', textContent:'', className:'', dataset:{}, style:{}, children:[], clientWidth:800, clientHeight:600, getContext(){return {clearRect(){}, fillRect(){}, beginPath(){}, moveTo(){}, lineTo(){}, stroke(){}, arc(){}, fill(){}};}, setAttribute(){}, append(...nodes){this.children.push(...nodes);}, replaceChildren(...nodes){this.children = nodes;}, replaceWith(){}};}
const elements = {tracks: element('div'), detail: element('section'), candidates: element('ol'), 'mood-strip': element('canvas'), 'mood-strip-picker': element('input'), 'mood-strip-value': element('output'), 'selected-mood': element('select'), 'genre-filter': element('select'), 'graph-info': element('p')};
context.document = {createElement: element, createTextNode(value){return {textContent:String(value)};}, querySelector(){return null;}, querySelectorAll(selector){assert.strictEqual(selector, '#tracks tr[data-track-id]'); return elements.tracks.children.length ? elements.tracks.children[0].children[2].children : [];}, getElementById(id){return elements[id] || null;}};
const rendered = [];
context.renderMap = data => rendered.push(data.nodes.map(n => n.id));
vm.runInContext('renderMap = globalThis.renderMap', context);
const click = context.setCurrent('b');
await Promise.resolve();
const staleRefresh = context.refresh();
await staleRefresh;
assert.strictEqual(vm.runInContext('state.current_track_id', context), 'b', 'refresh must preserve optimistic latest click while POST is pending');
assert.deepStrictEqual(elements.tracks.children[0].children[2].children.map(row => row.className), ['', 'current']);
postCurrent.resolve();
await click;
assert.strictEqual(vm.runInContext('state.current_track_id', context), 'b', 'POST response should remain latest selected track despite intervening refresh');
assert(elements.detail.children.some(child => child.textContent.includes('Current Track')), 'latest click detail must render after POST resolves');
assert(!fetches.some(path => path.startsWith('/api/candidates')), 'click does not request removed candidate list');
assert(fetches.includes('/api/state') && fetches.includes('/api/current'));
})().catch(error => { console.error(error); process.exit(1); });
""";
        subprocess.run(['node', '-e', script, str(APP_JS)], check=True, cwd=REPO_ROOT)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for history race tests')
    def test_late_history_response_does_not_overwrite_later_click_selection(self):
        script = r"""
const assert = require('assert');
const fs = require('fs'), vm = require('vm');
const context = {module:{exports:{}}, console, URLSearchParams, requestAnimationFrame(cb){Promise.resolve().then(cb);}};
(async () => {
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
function deferred(){let resolve; const promise = new Promise(r => {resolve = r;}); return {promise, resolve};}
function response(payload){return {ok:true, json:async()=>payload};}
function point(id){return {track_id:id, display_label:id.toUpperCase(), title:id, artist:'Artist', x:{raw:0, normalized:0.5, scale:'native', label:'valence'}, y:{raw:0, normalized:0.5, scale:'native', label:'arousal'}, z:{raw:120, normalized:0.5, scale:'raw', label:'BPM'}, mood_score:{label:'calm', raw:0.5, normalized:0.5}, genres:[]};}
const resetPost = deferred();
const clickPost = deferred();
const stateFetch = deferred();
const fetches = [];
context.fetch = (path, options={}) => {
  fetches.push(String(path));
  if (path === '/api/reset') return resetPost.promise.then(() => response({current_track_id:null}));
  if (path === '/api/current') return clickPost.promise.then(() => response({current_track_id:'b'}));
  if (path === '/api/state') return stateFetch.promise.then(() => response({current_track_id:'b'}));
  if (path === '/api/tracks/summary?limit=100&order=title') return Promise.resolve(response({tracks:[{handle:'a', display_label:'Aye'},{handle:'b', display_label:'Bee'}]}));
  if (path === '/api/mood-axis-graph') return Promise.resolve(response({positioned:[point('a'), point('b')], edges:[], selected_mood:'calm', available_moods:['calm']}));
  if (path === '/api/tracks/b') return Promise.resolve(response({handle:'b', display_label:'Bee', latest_run_status:'completed', available_locations:1, reasons:[], fields:{}}));
  if (String(path).startsWith('/api/candidates?')) return Promise.resolve(response({candidates:[{track_id:'cand-b', tier:'strong', score:0.8}]}));
  return Promise.reject(new Error('unexpected fetch '+path));
};
function element(tag){return {tag, id:'', textContent:'', className:'', dataset:{}, style:{}, children:[], clientWidth:800, clientHeight:600, value:'', options:[], getContext(){return {clearRect(){}, fillRect(){}, beginPath(){}, moveTo(){}, lineTo(){}, stroke(){}, arc(){}, fill(){}};}, setAttribute(){}, append(...nodes){this.children.push(...nodes);}, replaceChildren(...nodes){this.children = nodes;}, replaceWith(){}};}
const elements = {tracks: element('div'), detail: element('section'), candidates: element('ol'), 'mood-strip': element('canvas'), 'mood-strip-picker': element('input'), 'mood-strip-value': element('output'), 'selected-mood': element('select'), 'genre-filter': element('select'), 'graph-info': element('p'), controls: element('div'), undo: element('button'), reset: element('button')};
context.document = {createElement: element, createTextNode(value){return {textContent:String(value)};}, querySelector(){return null;}, querySelectorAll(selector){assert.strictEqual(selector, '#tracks tr[data-track-id]'); return elements.tracks.children.length ? elements.tracks.children[0].children[2].children : [];}, getElementById(id){return elements[id] || null;}};
vm.runInContext("if(typeof document!=='undefined'){document.getElementById('reset').onclick=()=>applyHistorySelection('/api/reset');}", context);
const reset = elements.reset.onclick();
await Promise.resolve();
const click = context.setCurrent('b');
await Promise.resolve();
assert.strictEqual(vm.runInContext('state.current_track_id', context), 'b', 'later click should become optimistic selection while reset POST is pending');
clickPost.resolve();
await click;
assert.strictEqual(vm.runInContext('state.current_track_id', context), 'b', 'later click POST should select b before stale reset response resolves');
resetPost.resolve();
await Promise.resolve();
assert.strictEqual(vm.runInContext('state.current_track_id', context), 'b', 'stale reset history response must not overwrite later click selection while its refresh is pending');
stateFetch.resolve();
await reset;
assert.strictEqual(vm.runInContext('state.current_track_id', context), 'b', 'stale reset history refresh must preserve later click selection');
assert(elements.detail.children.some(child => child.textContent.includes('Current Track')), 'latest click detail remains rendered after stale reset response');
assert(!fetches.some(path => path.startsWith('/api/candidates')), 'stale reset does not request removed candidate list');
assert(fetches.includes('/api/reset') && fetches.includes('/api/current'));
})().catch(error => { console.error(error); process.exit(1); });
""";
        subprocess.run(['node', '-e', script, str(APP_JS)], check=True, cwd=REPO_ROOT)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for reset race tests')
    def test_reset_invalidates_in_flight_click_post_continuation(self):
        script = r"""
const assert = require('assert');
const fs = require('fs'), vm = require('vm');
const context = {module:{exports:{}}, console, URLSearchParams, requestAnimationFrame(){}};
(async () => {
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
function deferred(){let resolve; const promise = new Promise(r => {resolve = r;}); return {promise, resolve};}
function response(payload){return {ok:true, json:async()=>payload};}
function point(id){return {track_id:id, display_label:id.toUpperCase(), title:id, artist:'Artist', x:{raw:0, normalized:0.5, scale:'native', label:'valence'}, y:{raw:0, normalized:0.5, scale:'native', label:'arousal'}, z:{raw:120, normalized:0.5, scale:'raw', label:'BPM'}, mood_score:{label:'calm', raw:0.5, normalized:0.5}, genres:[]};}
const postCurrent = deferred();
const fetches = [];
context.fetch = (path, options={}) => {
  fetches.push(String(path));
  if (path === '/api/current') return postCurrent.promise.then(() => response({current_track_id:'b'}));
  if (path === '/api/reset') return Promise.resolve(response({current_track_id:null}));
  if (path === '/api/state') return Promise.resolve(response({current_track_id:null}));
  if (path === '/api/tracks/summary?limit=100&order=title') return Promise.resolve(response({tracks:[{handle:'a', display_label:'Aye'},{handle:'b', display_label:'Bee'}]}));
  if (path === '/api/mood-axis-graph') return Promise.resolve(response({positioned:[point('a'), point('b')], edges:[], selected_mood:'calm', available_moods:['calm']}));
  if (path === '/api/tracks/b') return Promise.resolve(response({handle:'b', display_label:'Bee stale', latest_run_status:'completed', available_locations:1, reasons:[], fields:{}}));
  if (String(path).startsWith('/api/candidates?')) return Promise.resolve(response({candidates:[{track_id:'cand-b', tier:'stale', score:0.8}]}));
  return Promise.reject(new Error('unexpected fetch '+path));
};
function element(tag){return {tag, id:'', textContent:'', className:'', dataset:{}, style:{}, children:[], clientWidth:800, clientHeight:600, value:'', options:[], getContext(){return {clearRect(){}, fillRect(){}, beginPath(){}, moveTo(){}, lineTo(){}, stroke(){}, arc(){}, fill(){}};}, setAttribute(){}, append(...nodes){this.children.push(...nodes);}, replaceChildren(...nodes){this.children = nodes;}, replaceWith(){}};}
const elements = {tracks: element('div'), detail: element('section'), candidates: element('ol'), 'mood-strip': element('canvas'), 'mood-strip-picker': element('input'), 'mood-strip-value': element('output'), 'selected-mood': element('select'), 'genre-filter': element('select'), 'graph-info': element('p'), controls: element('div'), undo: element('button'), reset: element('button')};
context.document = {createElement: element, createTextNode(value){return {textContent:String(value)};}, querySelector(){return null;}, querySelectorAll(selector){assert.strictEqual(selector, '#tracks tr[data-track-id]'); return elements.tracks.children.length ? elements.tracks.children[0].children[2].children : [];}, getElementById(id){return elements[id] || null;}};
context.refresh = () => Promise.resolve();
vm.runInContext('refresh = globalThis.refresh', context);
vm.runInContext("if(typeof document!=='undefined'){document.getElementById('undo').onclick=()=>applyHistorySelection('/api/undo'); document.getElementById('reset').onclick=()=>applyHistorySelection('/api/reset');}", context);
const click = context.setCurrent('b');
await Promise.resolve();
await elements.reset.onclick();
assert.strictEqual(vm.runInContext('state.current_track_id', context), null, 'reset should clear selection while click POST is pending');
postCurrent.resolve();
await click;
assert.strictEqual(vm.runInContext('state.current_track_id', context), null, 'stale click POST continuation must not restore b after reset');
assert.deepStrictEqual(fetches.filter(path => path === '/api/tracks/b'), [], 'stale click continuation must not fetch stale track detail after reset');
assert(!elements.detail.children.some(node => node.textContent === 'Bee stale'), 'stale click detail must not render after reset');
assert(fetches.includes('/api/current') && fetches.includes('/api/reset'));
})().catch(error => { console.error(error); process.exit(1); });
"""
        subprocess.run(['node', '-e', script, str(APP_JS)], check=True, cwd=REPO_ROOT)

    def test_undo_and_reset_still_force_complete_ui_refresh(self):
        app = APP_JS.read_text()
        self.assertIn("async function applyHistorySelection(path){const token=++selectionRequestSeq; pendingSelectionIntent=null; const posted=syncSelectionEpoch(await api(path,{method:'POST'})); if(token!==selectionRequestSeq) return; state=posted; await refresh();}", app)
        self.assertIn("selection_epoch:selectionEpoch", app)
        self.assertIn("selection_client_id:selectionClientId()", app)
        self.assertIn("document.getElementById('undo').onclick=()=>applyHistorySelection('/api/undo');", app)
        self.assertIn("document.getElementById('reset').onclick=()=>applyHistorySelection('/api/reset');", app)

    def test_graph_color_legend_handles_ranged_axis_objects(self):
        script = r"""
const assert = require('assert');
const app = require(process.argv[1]);
const legend = app.graphColorLegend({colorRanges:{valence:{min:-0.5,max:0.75}, arousal:{min:0.1,max:1.9}}});
assert(legend.includes('-0.5 to 0.8 native'), legend);
assert(legend.includes('0.1 to 1.9 native'), legend);
assert(!legend.includes('undefined'), legend);
"""
        if shutil.which('node'):
            subprocess.run(['node', '-e', script, str(APP_JS)], check=True, cwd=REPO_ROOT)
        else:
            source = APP_JS.read_text(encoding='utf-8')
            self.assertIn('.min', source)
            self.assertIn('.max', source)

    def test_initial_detail_is_empty_without_selection_in_both_explorer_packages(self):
        script = r"""
const assert = require('assert');
const fs = require('fs'), vm = require('vm');
const context = {module:{exports:{}}, console};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
function element(tag){return {tag, textContent:'', className:'', children:[], append(...nodes){this.children.push(...nodes);}, replaceChildren(...nodes){this.children = nodes; this.textContent = '';}};}
const detail = element('section');
context.document = {createElement: element, getElementById(id){return id === 'detail' ? detail : null;}};
vm.runInContext("visibleGraph = {nodes:[{id:'a'}], links:[{}], unpositioned:[{track_id:'u', display_label:'Missing', reasons:['missing bpm']}]}", context);
context.renderInitialDetail({nodes:[{id:'a'}], links:[{}], unpositioned:[{track_id:'u', display_label:'Missing', reasons:['missing bpm']}], colorRanges:{valence:[-1,1], arousal:[0,2]}, selectedMood:'calm'});
const rendered = (function all(node){return [node.textContent,...(node.children||[]).flatMap(all)];})(detail).join(' ');
assert.strictEqual(rendered.trim(), '', rendered);
assert(!rendered.includes('All-library valence / arousal / BPM graph'), rendered);
assert(!rendered.includes('Showing'), rendered);
assert(!rendered.includes('missing bpm'), rendered);
assert(!rendered.includes('Missing'), rendered);
assert(!rendered.includes('Graph key / status'), rendered);
assert(!rendered.includes('Color relative to this library'), rendered);
"""
        if shutil.which('node'):
            for app in (APP_JS, REPO_ROOT / 'music_explorer/frameworks/explorer/assets/app.js'):
                with self.subTest(app=app):
                    subprocess.run(['node', '-e', script, str(app)], check=True, cwd=REPO_ROOT)
        else:
            for app in (APP_JS, REPO_ROOT / 'music_explorer/frameworks/explorer/assets/app.js'):
                source = app.read_text(encoding='utf-8')
                initial_source = source[source.index('function renderInitialDetail'):source.index('function fieldDisplay')]
                self.assertNotIn('Graph key / status', initial_source)
                self.assertNotIn('graphStatusParagraph(visibleGraph)', initial_source)
                self.assertNotIn('All-library valence / arousal / BPM graph', initial_source)
                self.assertNotIn('unpositioned', initial_source)

    def test_detail_dials_are_half_size_and_have_no_tick_styles(self):
        style = (REPO_ROOT / 'music_analyzer/frameworks/explorer/assets/style.css').read_text()
        self.assertIn('#detail .score-gauge{position:relative;width:39px;height:39px;', style)
        self.assertIn('@media(max-width:700px){#detail .score-gauge{width:34px;height:34px}', style)
        self.assertNotIn('.score-tick', style)

    def test_vanilla_js_detail_renderer_reads_nested_automatic_summary_values(self):
        script = r"""
const assert = require('assert');
const app = require(process.argv[1]);
const fs = require('fs');
const vm = require('vm');
const context = {module:{exports:{}}, console};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
function element(tag){
  return {tag, textContent:'', className:'', style:{}, setAttribute(){}, children:[], append(...nodes){this.children.push(...nodes);}, replaceChildren(...nodes){this.children = nodes;}};
}
const detail = element('section');
context.document = {createElement: element, getElementById(id){return id === 'detail' ? detail : null;}};
const auto = (pairs, provenance=[], key='summary_values') => ({automatic:{values:[],summary_values:[],provenance,[key]:pairs},effective_source:'automatic'});
const render = fields => context.renderDetail({handle:'track-1', display_label:'<track>',latest_run_status:'failed',available_locations:1,reasons:['evidence pending'], fields});
const all = node => [node,...node.children.flatMap(all)];
const nodes = () => all(detail);
const gauges = () => nodes().filter(n => n.className==='score-gauge');
render({
  genres:auto([['low',0.1],['mid',0.5],['high',1],['tie',1],['bad',Infinity],['out',1.1]], [['genre_discogs400-discogs-effnet-1','hash'],['threshold','0.5']]),
  mood:auto([['zero',0],['middle',0.5],['above',0.8],['invalid',-0.3]], [['mtg_jamendo_moodtheme-discogs-effnet-1','hash']]),
  energy:auto([['arousal',3.7],['valence',-0.6]], [['emomusic-msd-musicnn-2','hash']]),
  bpm:{automatic:{values:[['bpm',128]]},effective_source:'automatic'},
  key:{automatic:{values:[['key','C major']]},effective_source:'automatic'},
  instruments:auto([['guitar',0.9],['piano',0.1],['drums',0.2]], [['mtg_jamendo_instrument-discogs-effnet-1','hash']]),
  absent:{automatic:{values:[]},effective_source:'missing',missing_reason:'stage absent'}
});
assert(detail.children.some(child => child.textContent==='Current Track'), 'current track heading remains');
let rendered = nodes().map(n => n.textContent).join(' ');
assert(!rendered.includes('Status: failed') && !rendered.includes('evidence pending'));
assert(rendered.includes('mid') && rendered.includes('high') && rendered.includes('tie') && !rendered.includes('low') && !rendered.includes('out'));
assert(rendered.includes('middle') && rendered.includes('above') && !rendered.includes('zero'));
assert(rendered.includes('guitar') && rendered.includes('drums') && !rendered.includes('piano'));
assert(nodes().some(n=>n.className==='score-row' && n.children[0].textContent==='guitar'));
assert(!nodes().some(n=>n.className==='score-row' && n.children[0].textContent.includes(' / 1')));
assert(rendered.includes('native') && rendered.includes('3.7') && rendered.includes('-0.6'));
assert(rendered.includes('128') && rendered.includes('C major') && rendered.includes('no usable evidence') && rendered.includes('stage absent'));
assert(rendered.includes('display scores > 0.1') && rendered.includes('not probabilities'));
assert(!rendered.includes('stage threshold'));
assert(!rendered.includes('Infinity'));
assert.strictEqual(gauges().length,7);
assert(gauges().every(g=>g.tag==='div' && g.children.some(n=>n.className==='score-arc') && g.children.some(n=>n.className==='score-hub')));
assert(nodes().some(n=>n.textContent==='128.0 BPM (raw)'));

assert.deepStrictEqual(gauges().map(g => g.children.find(n => n.className==='score-needle').style.transform), ['rotate(120deg)','rotate(120deg)','rotate(0deg)','rotate(72deg)','rotate(0deg)','rotate(96deg)','rotate(-72deg)']);
assert(gauges().every(g => !g.children.some(n => n.className.startsWith('score-tick'))));
assert(gauges().every(g => !g.children.some(n => n.className==='score-threshold')));
render({genres:auto([['under',0.099],['at',0.1],['top',1],['just-above',0.1001],['round-up',0.05]], [['genre_discogs400-discogs-effnet-1','hash'],['threshold','0.7']]), mood:auto([['x',0.9]], [['unknown','hash']])});
rendered = nodes().map(n => n.textContent).join(' ');
assert(!rendered.includes('under:') && !rendered.includes('at:') && nodes().some(n=>n.className==='score-row' && n.children[0].textContent==='just-above') && rendered.includes('no usable evidence'));
assert.strictEqual(gauges().length,2);
render({genres:auto([['wrong-model',0.95]], [['model','other'],['genre_discogs400-discogs-effnet-1','hash']])});
assert.strictEqual(gauges().length,0);
assert(nodes().some(n => n.textContent.includes('no usable evidence')));
render({mood:auto([['wrong-scale',0.8]], [['mtg_jamendo_moodtheme-discogs-effnet-1','hash'],['scale','native_valence_arousal_regression']]),instruments:auto([['wrong',0.7]], [['mtg_jamendo_instrument-discogs-effnet-1','hash'],['model','other']]),energy:auto([['arousal',3.7]], [['emomusic-msd-musicnn-2','hash'],['scale','sigmoid_mean_score_0_1']])});
assert.strictEqual(gauges().length,0);
assert(!nodes().some(n=>n.textContent==='arousal: 3.7'));
render({instruments:auto([['wrong',0.7]], [['unsupported','hash']]),mood:auto([['finite',0.2]], [['mtg_jamendo_moodtheme-discogs-effnet-1','hash']])});
assert.strictEqual(gauges().length,1);
assert(!nodes().some(n=>n.textContent==='wrong'));
render({genres:{...auto([['automatic',1]], [['genre_discogs400-discogs-effnet-1','hash']]),manual_text:'<script>chosen</script>',effective_source:'manual_text',typed_override_status:'unresolved'},mood:auto([['tiny',0.2]], [['mtg_jamendo_moodtheme-discogs-effnet-1','hash'],['scale','sigmoid_mean_score_0_1']])});
rendered = nodes().map(n => n.textContent).join(' ');
assert(rendered.includes('<script>chosen</script>') && rendered.includes('unresolved') && !rendered.includes('automatic: 1'));
assert(nodes().some(n=>n.className==='score-row' && n.children[0].textContent==='tiny') && rendered.includes('display scores > 0.1'));
assert.strictEqual(gauges().length,1);
render({genres:auto([['zero',0],['half',0.5],['one',1]], [['genre_discogs400-discogs-effnet-1','hash'],['threshold','0']])});
assert.deepStrictEqual(gauges().map(g => g.children.find(n => n.className==='score-needle').style.transform), ['rotate(120deg)','rotate(0deg)']);
render({genres:auto(Array.from({length:15},(_,i)=>['label'+i,0.9]), [['genre_discogs400-discogs-effnet-1','hash']])});
assert.strictEqual(gauges().length,12);
assert(nodes().some(n => n.textContent.includes('3 more significant labels not shown')));
assert.strictEqual(context.detailGauge('zero',0,0.1).children.find(n=>n.className==='score-gauge').children.find(n=>n.className==='score-needle').style.transform,'rotate(-120deg)');
assert.strictEqual(context.detailGauge('half',0.5,0.1).children.find(n=>n.className==='score-gauge').children.find(n=>n.className==='score-needle').style.transform,'rotate(0deg)');
assert.deepStrictEqual(app.graphDimensions({clientWidth: 1374, clientHeight: 520, parentElement: {clientWidth: 734}}), {width: 734, height: 520});
assert.deepStrictEqual(app.graphDimensions({clientWidth: 900, clientHeight: 0}), {width: 900, height: 1040});
const parentStyle = {paddingLeft:'16px', paddingRight:'16px', borderLeftWidth:'1px', borderRightWidth:'1px'};
global.getComputedStyle = elem => elem.computedStyle || {paddingLeft:'0px', paddingRight:'0px', borderLeftWidth:'0px', borderRightWidth:'0px'};
assert.deepStrictEqual(app.graphDimensions({clientWidth: 1374, clientHeight: 520, parentElement: {clientWidth: 768, computedStyle: parentStyle}}), {width: 734, height: 520});
assert.deepStrictEqual(app.graphDimensions({clientWidth: 534, clientHeight: 520, parentElement: {clientWidth: 568, computedStyle: parentStyle}}), {width: 534, height: 520});
""";
        if shutil.which('node'):
            subprocess.run(['node', '-e', script, str(APP_JS)], check=True, cwd=REPO_ROOT)
        else:
            source = APP_JS.read_text(encoding='utf-8')
            self.assertIn('if(a.summary_values&&a.summary_values.length) return a.summary_values', source)
            self.assertIn('const parent=elem&&elem.parentElement', source)
            self.assertIn('fieldDisplay', source[source.index('module.exports'):])







    def test_browser_startup_source_uses_compact_summary_before_graph(self):
        for app in (APP_JS, REPO_ROOT / 'music_explorer/frameworks/explorer/assets/app.js'):
            with self.subTest(app=app):
                source = app.read_text(encoding='utf-8')
                refresh_source = source[source.index('async function refresh()'):source.index('function trackTitle')]
                self.assertIn("const list=await api('/api/tracks/summary?limit=100&order=title')", refresh_source)
                self.assertNotIn("/api/tracks?limit=all", refresh_source)
                self.assertNotIn("/api/mood-axis-graph", refresh_source, 'startup refresh must not request graph before user clicks Load graph')
                self.assertIn('renderGraphLoadStatus()', refresh_source)
                load_graph_source = source[source.index('async function loadGraph()'):source.index('function renderInitialDetail')]
                self.assertIn("const controlQuery=graphQueryFromControls()", load_graph_source)
                self.assertIn("const graph=await api('/api/mood-axis-graph'+controlQuery+(controlQuery?'&':'?')+'contract=v2')", load_graph_source)
                self.assertIn('load-graph', source)
                self.assertIn('Load graph', source)
                self.assertIn('loadGraph', source[source.index('module.exports'):])
                self.assertIn('getStateForTesting', source[source.index('module.exports'):])

    @unittest.skipUnless(shutil.which('node'), 'Node is required for compact summary startup tests')
    def test_initial_refresh_renders_summary_list_and_detail_before_graph_resolves(self):
        script = r"""
const assert = require('assert');
const app = require(process.argv[1]);
function makeElement(tag){
  return {tagName: tag.toUpperCase(), children: [], parentElement: null, attributes: {}, dataset: {}, style: {}, id: '', hidden: false, value: '', selectedOptions: [], textContent: '', onclick: null, oninput: null, onchange: null, clientWidth: 900, clientHeight: 700, width: 0, height: 0,
    classList: {add(){}, remove(){}, contains(){return false;}},
    append(...nodes){for (const node of nodes) { if (node && typeof node === 'object') node.parentElement = this; this.children.push(node); }},
    replaceChildren(...nodes){this.children = []; this.append(...nodes);},
    replaceWith(node){if(this.parentElement){const siblings=this.parentElement.children; const index=siblings.indexOf(this); if(index >= 0) siblings.splice(index, 1, node); if(node && typeof node === 'object') node.parentElement = this.parentElement;}},
    setAttribute(name, value){this.attributes[name] = String(value);}, removeAttribute(name){delete this.attributes[name];},
    getContext(){return {clearRect(){}, fillRect(){}, beginPath(){}, arc(){}, fill(){}, stroke(){}, moveTo(){}, lineTo(){}, set fillStyle(_v){}, set strokeStyle(_v){}};},
    querySelector(selector){if(selector === 'button') return this.children.flatMap(c => c.children || []).find(c => c.tagName === 'BUTTON') || null; return null;}
  };
}
function deferred(){let resolve; const promise = new Promise(r => {resolve = r;}); return {promise, resolve};}
function response(payload){return {ok:true, json:async()=>payload};}
const elements = {};
for (const id of ['library-loading','loading-status','loading-error','loading-retry','tracks','detail','map','track-search','selected-mood','genre-filter','mood-strip','mood-strip-picker','mood-strip-value']) { elements[id] = makeElement(id === 'map' || id === 'mood-strip' ? 'canvas' : id === 'track-search' ? 'input' : 'div'); elements[id].id = id; }
elements.map.parentElement = makeElement('div');
global.document = {createElement: makeElement, createTextNode: text => ({textContent: String(text)}), getElementById: id => elements[id] || null, querySelectorAll: () => []};
const frames = [];
global.requestAnimationFrame = cb => frames.push(cb);
function runNextFrame(){assert(frames.length, 'expected an animation frame callback'); frames.shift()();}
async function waitFor(condition, message){for(let i=0;i<30;i++){if(condition()) return; await Promise.resolve();} assert(condition(), message);}
const fetches = [];
global.fetch = path => {
  fetches.push(String(path));
  if (path === '/api/state') return Promise.resolve(response({current_track_id:'off-page', history:['previous'], selection_epoch:4}));
  if (path === '/api/tracks/summary?limit=100&order=title') return Promise.resolve(response({tracks:[{handle:'visible', title:'Visible Song', artist:'Visible Artist'}], next_cursor:'visible'}));
  if (path === '/api/tracks/off-page') return Promise.resolve(response({handle:'off-page', metadata:{common:[['title','Off Page Detail']], tags:[]}, fields:{}}));
  return Promise.reject(new Error('unexpected fetch '+path));
};
(async () => {
  const refresh = app.refresh();
  runNextFrame();
  await refresh;
  assert(fetches.includes('/api/tracks/summary?limit=100&order=title'), 'initial list uses compact summary API');
  assert(!fetches.includes('/api/tracks?limit=all'), 'initial list must not use unbounded full track API');
  assert(!fetches.includes('/api/mood-axis-graph'), 'startup must not decide to trigger the graph for large libraries');
  const rows = elements.tracks.children[0].children[2].children;
  assert.deepStrictEqual(rows.map(row => row.dataset.trackId), ['visible']);
  assert.strictEqual(rows[0].className, '', 'off-page selection is preserved without pretending visible row is current');
  assert(elements.detail.children.some(child => child.textContent.includes('Current Track')), 'selected detail renders without graph data');
  assert.strictEqual(app.getStateForTesting().current_track_id, 'off-page');
  assert.deepStrictEqual(app.getStateForTesting().history, ['previous']);
  assert.strictEqual(elements['track-search'].oninput && typeof elements['track-search'].oninput, 'function', 'list search is usable without graph');
})().catch(error => { console.error(error); process.exit(1); });
"""
        subprocess.run(['node', '-e', script, str(APP_JS)], check=True, cwd=REPO_ROOT)


    @unittest.skipUnless(shutil.which('node'), 'Node is required for loading screen DOM tests')
    def test_loading_screen_yields_before_fetch_rendering_graph_and_reports_honest_stages(self):
        script = r"""
const assert = require('assert');
const app = require(process.argv[1]);
function makeElement(tag){
  const classes = new Set();
  return {tagName: tag.toUpperCase(), children: [], parentElement: null, attributes: {}, dataset: {}, style: {}, id: '', hidden: false, value: '', selectedOptions: [], textContent: '', onclick: null, clientWidth: 900, clientHeight: 700, width: 0, height: 0,
    classList: {add: c => classes.add(c), remove: c => classes.delete(c), contains: c => classes.has(c)},
    append(...nodes){for (const node of nodes) { if (node && typeof node === 'object') node.parentElement = this; this.children.push(node); }},
    replaceChildren(...nodes){this.children = []; this.append(...nodes);},
    replaceWith(node){if(this.parentElement){const siblings=this.parentElement.children; const index=siblings.indexOf(this); if(index >= 0) siblings.splice(index, 1, node); if(node && typeof node === 'object') node.parentElement = this.parentElement;}},
    setAttribute(name, value){this.attributes[name] = String(value);}, removeAttribute(name){delete this.attributes[name];},
    getContext(){return {clearRect(){}, fillRect(){}, beginPath(){}, arc(){}, fill(){}, stroke(){}, moveTo(){}, lineTo(){}, set fillStyle(_v){}, set strokeStyle(_v){}};},
    querySelector(){return null;}
  };
}
const elements = {};
for (const id of ['library-loading','loading-status','loading-error','loading-retry','tracks','detail','map']) { elements[id] = makeElement(id === 'map' ? 'canvas' : 'div'); elements[id].id = id; }
elements.map.parentElement = makeElement('div');
global.document = {createElement: makeElement, createTextNode: text => ({textContent: String(text)}), getElementById: id => elements[id] || null, querySelectorAll: () => []};
const frames = [];
global.requestAnimationFrame = cb => frames.push(cb);
function runNextFrame(){assert(frames.length, 'expected an animation frame callback'); frames.shift()();}
async function waitFor(condition, message){for(let i=0;i<20;i++){if(condition()) return; await Promise.resolve();} assert(condition(), message);}
const calls = [];
const graph = {selected_mood:'', available_moods:[], metadata:{}, unpositioned:[], positioned:[{track_id:'a',display_label:'Alpha',x:{raw:0.5,normalized:0.5,scale:'native'},y:{raw:0.4,normalized:0.4,scale:'native'},z:{label:'BPM',raw:120,normalized:6,scale:'fixed'},mood_score:null,bpm:120,genres:[],reasons:[]}], edges:[]};
global.fetch = async path => { calls.push(String(path)); return {ok:true, json: async () => path === '/api/state' ? {current_track_id:null} : path.startsWith('/api/tracks') ? {tracks:[{handle:'a',title:'Alpha',artist:'Artist'}]} : graph}; };
(async () => {
  const promise = app.refresh();
  assert.match(elements['loading-status'].textContent, /Preparing/);
  assert.deepStrictEqual(calls, [], 'loading status must be paintable before network fetches start');
  runNextFrame();
  await waitFor(() => calls.length === 2, 'refresh should fetch state and compact summary only after the first frame');
  assert.deepStrictEqual(calls, ['/api/state','/api/tracks/summary?limit=100&order=title']);
  assert(!calls.includes('/api/mood-axis-graph'), 'refresh must not load graph before explicit user click');
  await promise;
  assert(elements['library-loading'].classList.contains('done'));
  assert.strictEqual(elements['library-loading'].attributes['aria-busy'], 'false');
})().catch(error => { console.error(error); process.exit(1); });
"""
        subprocess.run(['node', '-e', script, str(APP_JS)], check=True, cwd=REPO_ROOT)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for loading screen DOM tests')
    def test_stale_refresh_and_errors_do_not_clear_newer_loading_and_retry_is_accessible(self):
        script = r"""
const assert = require('assert');
const app = require(process.argv[1]);
function makeElement(tag){const classes = new Set(); return {tagName: tag.toUpperCase(), children: [], parentElement: null, attributes: {}, dataset: {}, style: {}, id: '', hidden: false, value: '', textContent: '', onclick: null, clientWidth: 900, clientHeight: 700, width: 0, height: 0, classList: {add: c => classes.add(c), remove: c => classes.delete(c), contains: c => classes.has(c)}, append(...nodes){for (const node of nodes) { if (node && typeof node === 'object') node.parentElement = this; this.children.push(node); }}, replaceChildren(...nodes){this.children = []; this.append(...nodes);}, setAttribute(name, value){this.attributes[name] = String(value);}, removeAttribute(name){delete this.attributes[name];}, getContext(){return {clearRect(){}, fillRect(){}, beginPath(){}, arc(){}, fill(){}, stroke(){}, moveTo(){}, lineTo(){}};}, querySelector(){return null;}};}
const elements = {};
for (const id of ['library-loading','loading-status','loading-error','loading-retry','tracks','detail','map']) { elements[id] = makeElement(id === 'map' ? 'canvas' : 'div'); elements[id].id = id; }
elements.map.parentElement = makeElement('div');
global.document = {createElement: makeElement, createTextNode: text => ({textContent: String(text)}), getElementById: id => elements[id] || null, querySelectorAll: () => []};
const frames = [];
global.requestAnimationFrame = cb => frames.push(cb);
function runNextFrame(){assert(frames.length, 'expected an animation frame callback'); frames.shift()();}
async function waitForPending(count){for(let i=0;i<20 && pending.length<count;i++) await Promise.resolve(); assert.strictEqual(pending.length, count, `expected ${count} pending fetches`);}
const pending = [];
global.fetch = path => new Promise((resolve, reject) => pending.push({path: String(path), resolve, reject}));
const ok = body => ({ok:true, json: async () => body});
const graph = {positioned: [], edges: [], unpositioned: [], available_moods: [], selected_mood: '', metadata: {}};
(async () => {
  const first = app.refresh();
  assert.strictEqual(pending.length, 0, 'first refresh waits for the paint frame before fetching');
  runNextFrame();
  await waitForPending(1);
  const second = app.refresh();
  assert.strictEqual(pending.length, 1, 'newer refresh also waits for its paint frame before fetching');
  runNextFrame();
  await waitForPending(2);
  pending[0].resolve(ok({current_track_id:'old'}));
  await first;
  assert(!elements['library-loading'].classList.contains('done'), 'stale refresh must not hide newer loading');
  pending[1].resolve(ok({current_track_id:null})); await waitForPending(3);
  pending[2].resolve(ok({tracks:[]})); await second;
  assert(elements['library-loading'].classList.contains('done'), 'newest refresh may clear loading');
  const failing = app.refresh().catch(error => error);
  runNextFrame();
  await waitForPending(4);
  pending[3].reject(new Error('network down'));
  const error = await failing;
  assert.match(error.message, /network down/);
  assert.strictEqual(elements['library-loading'].attributes['aria-busy'], 'false');
  assert.match(elements['loading-status'].textContent, /Unable to load/);
  assert.strictEqual(elements['loading-retry'].hidden, false);
  assert.strictEqual(typeof elements['loading-retry'].onclick, 'function');
})().catch(error => { console.error(error); process.exit(1); });
"""
        subprocess.run(['node', '-e', script, str(APP_JS)], check=True, cwd=REPO_ROOT)


    def test_load_graph_requests_opt_in_compact_v2_contract_in_standalone_and_analyzer_assets(self):
        """RED: the browser must negotiate the compact graph DTO explicitly.

        This source-level guard still runs in environments without Node. The
        Node-backed tests below exercise the same contract through loadGraph's
        public test seam when Node is available.
        """
        for app in (APP_JS, REPO_ROOT / 'music_explorer/frameworks/explorer/assets/app.js'):
            with self.subTest(app=app):
                source = app.read_text(encoding='utf-8')
                start = source.index('async function loadGraph()')
                end = source.index('function applyCurrentGraphFilters()', start)
                load_graph = source[start:end]
                self.assertIn('contract=v2', load_graph, 'loadGraph must opt in to the compact graph HTTP contract')
                self.assertNotIn("api('/api/mood-axis-graph'+graphQueryFromControls())", load_graph, 'loadGraph must not silently use the legacy verbose graph endpoint')

    @unittest.skipUnless(shutil.which('node'), 'Node is required for compact graph DTO parity tests')
    def test_compact_graph_dto_normalizes_to_existing_verbose_graph_model(self):
        script = r"""
const assert = require('assert');
const app = require(process.argv[1]);
const legacy = {
  selected_mood:'relaxing',
  available_moods:['relaxing','heavy'],
  metadata:{graph_status:{state:'ready'}, source_revision:'rev-1', fingerprint:'fp-1'},
  positioned:[
    {track_id:'a', display_label:'Alpha', x:{raw:-0.5, normalized:0.25, scale:'native'}, y:{raw:0.75, normalized:0.875, scale:'native'}, z:{label:'BPM', raw:120, normalized:6, scale:'fixed-BPM/20-display-units'}, mood_score:{label:'relaxing',raw:0.9,normalized:0.9}, bpm:120, genres:[['rock',0.6]], genre_threshold:0.5, reasons:['energy available']},
    {track_id:'b', display_label:'Beta', x:{raw:0.5, normalized:0.75, scale:'native'}, y:{raw:-0.25, normalized:0.375, scale:'native'}, z:{label:'BPM', raw:140, normalized:7, scale:'fixed-BPM/20-display-units'}, mood_score:{label:'relaxing',raw:0.2,normalized:0.2}, bpm:140, genres:[['jazz',0.7]], genre_threshold:0.5, reasons:['genre threshold met']}
  ],
  unpositioned:[{track_id:'c', display_label:'Gamma', reasons:['missing energy']}],
  edges:[{a:'a', b:'b', score:0.77, explanation:'warm cache', provenance:[['edge-cache','synthetic']], supported_group_count:3}]
};
const compact = {
  dto_version:'mood-axis-graph-compact-v1',
  selected_mood:legacy.selected_mood,
  available_moods:legacy.available_moods,
  metadata:legacy.metadata,
  nodes: legacy.positioned.map(n => ({
    id:n.track_id, label:n.display_label, x:n.x, y:n.y, z:n.z,
    bpm:n.bpm, genres:n.genres, genre_threshold:n.genre_threshold,
    mood_score:n.mood_score, reasons:n.reasons
  })),
  unpositioned:[{id:'c', label:'Gamma', reasons:['missing energy']}],
  links:[{source:'a', target:'b', score:0.77, explanation:'warm cache', provenance:[['edge-cache','synthetic']], supported_group_count:3}]
};
assert.strictEqual(typeof app.normalizeMoodAxisGraphDto, 'function', 'normalizer must be exported through the browser asset test seam');
const normalized = app.normalizeMoodAxisGraphDto(compact);
assert.deepStrictEqual(normalized, legacy, 'compact DTO normalizes to the existing verbose graph shape before model building');
const compactModel = app.buildMoodGraphModel(normalized);
const verboseModel = app.buildMoodGraphModel(legacy);
assert.deepStrictEqual(compactModel.nodes.map(n => [n.id,n.label,n.x,n.y,n.z,n.bpm,n.genres,n.moodScore.raw,n.reasons]), verboseModel.nodes.map(n => [n.id,n.label,n.x,n.y,n.z,n.bpm,n.genres,n.moodScore.raw,n.reasons]));
assert.deepStrictEqual(compactModel.links, verboseModel.links);
assert.deepStrictEqual(compactModel.unpositioned, verboseModel.unpositioned);
assert.deepStrictEqual(app.applyMoodGraphFilters(compactModel,{bpmMin:130,genres:['jazz']}).nodes.map(n=>n.id), ['b']);
assert.throws(() => app.normalizeMoodAxisGraphDto({dto_version:'mood-axis-graph-compact-v999', nodes:[], links:[]}), /unknown|unsupported|dto/i);
"""
        for app in (APP_JS, REPO_ROOT / 'music_explorer/frameworks/explorer/assets/app.js'):
            with self.subTest(app=app):
                subprocess.run(['node', '-e', script, str(app)], check=True, cwd=REPO_ROOT)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for compact graph request negotiation tests')
    def test_load_graph_fetches_compact_v2_contract_and_preserves_single_in_flight_graph_request(self):
        script = r"""
const assert = require('assert');
const app = require(process.argv[1]);
function makeElement(tag){
  const el = {tagName:tag.toUpperCase(), children:[], attributes:{}, dataset:{}, className:'', id:'', value:'', selected:false, selectedOptions:[], multiple:false, size:0, type:'', placeholder:'', textContent:'', onclick:null, onchange:null, parentElement:null, clientWidth:900, clientHeight:700,
    append(...nodes){for (const node of nodes) { if (node && typeof node === 'object') node.parentElement = this; this.children.push(node); }},
    replaceChildren(...nodes){this.children=[]; this.textContent=''; this.append(...nodes);},
    setAttribute(name,value){this.attributes[name]=String(value);},
    removeAttribute(name){delete this.attributes[name];},
    getContext(){return {clearRect(){}, fillRect(){}, beginPath(){}, moveTo(){}, lineTo(){}, stroke(){}, arc(){}, fill(){}};},
    get innerText(){return [this.textContent, ...this.children.map(c=>c.innerText || c.textContent || '')].filter(Boolean).join(' ');}
  };
  return el;
}
const elements = {'graph-load-status': makeElement('section'), graph3d: makeElement('div'), map: makeElement('canvas'), 'mood-strip': null, 'mood-strip-picker': null, 'mood-strip-value': null};
global.document = {createElement: makeElement, getElementById:id=>elements[id]||null, querySelectorAll:()=>[]};
global.requestAnimationFrame = cb => cb();
global.ForceGraph3D = undefined;
app.setGraphControlsForTesting({mood:'heavy', bpmMin:null, bpmMax:null, genres:[]});
const requests = [];
global.fetch = async path => {
  requests.push(String(path));
  return {ok:true, json:async()=>({dto_version:'mood-axis-graph-compact-v1', selected_mood:'heavy', available_moods:['heavy'], metadata:{graph_status:{state:'ready'}}, nodes:[{id:'a', label:'Alpha', x:{raw:0,normalized:0.5}, y:{raw:0,normalized:0.5}, z:{label:'BPM',raw:120,normalized:6}, mood_score:{label:'heavy',raw:0.8}, bpm:120, genres:[], genre_threshold:0.5, reasons:[]}], links:[], unpositioned:[]})};
};
(async()=>{
  const first = app.loadGraph();
  const second = app.loadGraph();
  await Promise.all([first, second]);
  assert(requests.every(path => path.startsWith('/api/mood-axis-graph')), 'only graph requests are issued by loadGraph');
  assert(requests.every(path => /(?:\?|&)contract=v2(?:&|$)/.test(path)), 'each graph request explicitly opts into compact v2');
  assert(requests.every(path => /(?:\?|&)mood=heavy(?:&|$)/.test(path)), 'compact negotiation preserves selected mood query');
  assert(!requests.some(path => path === '/api/mood-axis-graph' || path === '/api/mood-axis-graph?mood=heavy'), 'browser must not fall back to the legacy verbose graph URL');
  assert.deepStrictEqual(app.getVisibleGraphForTesting().nodes.map(n=>n.id), ['a']);
})().catch(error => { console.error(error); process.exit(1); });
"""
        for app in (APP_JS, REPO_ROOT / 'music_explorer/frameworks/explorer/assets/app.js'):
            with self.subTest(app=app):
                subprocess.run(['node', '-e', script, str(app)], check=True, cwd=REPO_ROOT)


if __name__ == '__main__':
    unittest.main()
