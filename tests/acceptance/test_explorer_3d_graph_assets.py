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
                ('energy', {'stage': 'energy', 'provenance': [['emomusic-msd-musicnn-2', 'synthetic-sha256'], ['scale', 'native_valence_arousal_regression']], 'uncertainty': '', 'values': [], 'summary': summary(('arousal', 'valence'), (arousal, valence))}),
                ('genres', {'stage': 'genres', 'provenance': [['genre_discogs400-discogs-effnet-1', 'synthetic-sha256'], ['threshold', '0.5']], 'uncertainty': '', 'values': [], 'summary': summary(('rock', 'jazz'), genre)}),
                ('mood', {'stage': 'mood', 'provenance': [['mtg_jamendo_moodtheme-discogs-effnet-1', 'synthetic-sha256'], ['scale', 'sigmoid_mean_score_0_1']], 'uncertainty': '', 'values': [], 'summary': summary(('relaxing', 'heavy'), mood)}),
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
const payload = {selected_mood:'relaxing', available_moods:['relaxing','heavy'], metadata:{}, unpositioned:[{track_id:'c',display_label:'Missing',reasons:['mood: no supported labels available']}], positioned:[
  {track_id:'a', display_label:'Alpha', x:{raw:0.7, normalized:0.7, scale:'native'}, y:{raw:0.2, normalized:0.2, scale:'native'}, z:{label:'BPM', raw:120, normalized:6, scale:'fixed-BPM/20-display-units'}, mood_score:{label:'relaxing',raw:0.9,normalized:0.9}, bpm:120, genres:[['rock',0.6]], genre_threshold:0.5, reasons:[]},
  {track_id:'b', display_label:'Beta', x:{raw:0.3, normalized:0.3, scale:'native'}, y:{raw:0.4, normalized:0.4, scale:'native'}, z:{label:'BPM', raw:130, normalized:6.5, scale:'fixed-BPM/20-display-units'}, mood_score:{label:'relaxing',raw:0.2,normalized:0.2}, bpm:130, genres:[['jazz',0.7]], genre_threshold:0.5, reasons:[]}
], edges:[{a:'a',b:'b',score:0.77,explanation:'axis-independent relatedness',supported_group_count:3}]};
const model = graph.buildMoodGraphModel(payload);
assert.deepStrictEqual(model.nodes.map(n => n.id), ['a','b']);
assert(model.nodes.every(n => Math.abs(n.x) > 1), 'render coordinates are scaled for browser visibility');
assert.strictEqual(model.nodes[0].x, model.nodes[0].axis.x.normalized * 180, 'X display spacing remains unchanged');
assert.strictEqual(model.nodes[0].fx, model.nodes[0].x, 'fixed X coordinate matches displayed X');
assert.strictEqual(model.nodes[0].y, model.nodes[0].axis.y.normalized * 180, 'Y display spacing is unchanged');
const before = new Map(model.nodes.map(n => [n.id, JSON.stringify([n.x,n.y,n.z,n.fx,n.fy,n.fz])]));
for (const node of model.nodes) {
  assert.strictEqual(node.z, node.axis.z.normalized * 360, 'fixed BPM depth is half its previous display scale');
  assert.strictEqual(node.fz, node.z, 'fixed simulation depth must match displayed depth');
}
assert.strictEqual(model.nodes[1].z-model.nodes[0].z, 180, '10 BPM retains visible depth at half scale');
const other = graph.buildMoodGraphModel({...payload,selected_mood:'heavy',positioned:payload.positioned.map(n=>({...n,mood_score:{label:'heavy',raw:0.5,normalized:0.5}}))});
assert.deepStrictEqual(other.nodes.map(n=>[n.id,n.x,n.y,n.z,n.fx,n.fy,n.fz]),model.nodes.map(n=>[n.id,n.x,n.y,n.z,n.fx,n.fy,n.fz]));
assert.deepStrictEqual(graph.graphCameraFrame(other.nodes,{width:900,height:700},50),graph.graphCameraFrame(model.nodes,{width:900,height:700},50));
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
assert.deepStrictEqual(app.graphAxisSpec([{x:36,y:54,z:4320},{x:126,y:90,z:4608}]).map(a=>a.references),[['0.2','0.7'],['0.3','0.5'],['120.0','128.0']]);

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
assert(info.textContent.includes('relative to this library'));
assert(info.textContent.includes('-2.0 to 3.0'));
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
context.document = {createElement: element, querySelector(){return null;}, querySelectorAll(selector){assert.strictEqual(selector, '#tracks li[data-track-id]'); return rows;}, getElementById(id){return elements[id] || element(id);}};
vm.runInContext("state={current_track_id:'server-current'}; selectionEpoch=0; graphModel={nodes:[{id:'client-click',moodScore:null},{id:'server-current',moodScore:null}],links:[],unpositioned:[],selectedMood:'',colorRanges:{}}; visibleGraph={nodes:graphModel.nodes,links:[],unpositioned:[]};", context);
const click = context.setCurrent('client-click');
await Promise.resolve();
assert.strictEqual(vm.runInContext('state.current_track_id', context), 'client-click', 'selection is optimistic before the server responds');
resolveCurrent();
await click;
assert.strictEqual(vm.runInContext('state.current_track_id', context), 'server-current', 'rejected/stale server snapshot must restore the accepted server selection');
assert.deepStrictEqual(rows.map(r => r.className), ['', 'current']);
assert(fetches.includes('/api/tracks/server-current'), 'detail fetch follows the accepted server snapshot after rejection');
assert.strictEqual(detail.children[0].textContent, 'Server Current');
})().catch(error => { console.error(error); process.exit(1); });
""";
        subprocess.run(['node', '-e', script, str(APP_JS)], check=True, cwd=REPO_ROOT)


    @unittest.skipUnless(shutil.which('node'), 'Node is required for selection rejection refresh tests')
    def test_refresh_after_rejected_selection_uses_authoritative_server_selection(self):
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
function point(id){return {track_id:id, display_label:id.toUpperCase(), title:id, artist:'Artist', x:{raw:0, normalized:0.5, scale:'native', label:'valence'}, y:{raw:0, normalized:0.5, scale:'native', label:'arousal'}, z:{raw:120, normalized:0.5, scale:'raw', label:'BPM'}, mood_score:{label:'calm', raw:0.5, normalized:0.5}, genres:[]};}
const fetches = [];
context.fetch = (path, options={}) => {
  fetches.push(String(path));
  if (path === '/api/current') return Promise.resolve(response({current_track_id:'server-current', selection_epoch:2, selection_accepted:false}));
  if (path === '/api/state') return Promise.resolve(response({current_track_id:'server-current', selection_epoch:2}));
  if (path === '/api/tracks?limit=all') return Promise.resolve(response({tracks:[{handle:'client-click', display_label:'Client Click'},{handle:'server-current', display_label:'Server Current'}]}));
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
const elements = {tracks: element('ul'), detail: element('section'), candidates: element('ol'), 'mood-strip': element('canvas'), 'mood-strip-picker': element('input'), 'mood-strip-value': element('output'), 'selected-mood': element('select'), 'genre-filter': element('select'), 'graph-info': element('p')};
context.document = {createElement: element, createTextNode(value){return {textContent:String(value)};}, querySelector(){return null;}, querySelectorAll(selector){assert.strictEqual(selector, '#tracks li[data-track-id]'); return elements.tracks.children;}, getElementById(id){return elements[id] || null;}};
vm.runInContext("state={current_track_id:'server-current'}; selectionEpoch=1; graphModel={nodes:[{id:'client-click',moodScore:null},{id:'server-current',moodScore:null}],links:[],unpositioned:[],selectedMood:'',colorRanges:{}}; visibleGraph={nodes:graphModel.nodes,links:[],unpositioned:[]};", context);
await context.setCurrent('client-click');
assert.strictEqual(vm.runInContext('state.current_track_id', context), 'server-current', 'rejected POST restores authoritative server selection');
await context.refresh();
assert.strictEqual(vm.runInContext('state.current_track_id', context), 'server-current', 'refresh after rejection must not overlay the rejected click intent');
assert.deepStrictEqual(elements.tracks.children.map(row => row.className), ['', 'current']);
assert(elements.detail.children[0].textContent === 'Server Current', 'detail follows authoritative server selection after refresh');
assert(elements.candidates.children[0].textContent.includes('server-candidate'), 'candidates follow authoritative server selection after refresh');
assert(fetches.includes('/api/current') && fetches.includes('/api/state'));
})().catch(error => { console.error(error); process.exit(1); });
"""
        subprocess.run(['node', '-e', script, str(APP_JS)], check=True, cwd=REPO_ROOT)


    @unittest.skipUnless(shutil.which('node'), 'Node is required for selection behavior tests')
    def test_selection_only_fetches_detail_candidates_and_keeps_graph_data(self):
        script = r"""
const assert = require('assert');
const fs = require('fs'), vm = require('vm');
const context = {module:{exports:{}}, console, URLSearchParams};
(async () => {
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
function deferred(){let resolve; const promise = new Promise(r => {resolve = r;}); return {promise, resolve};}
function response(payload){return {ok:true, json:async()=>payload};}
const detailA = deferred(), candidatesA = deferred();
const fetches = [];
context.fetch = (path, options={}) => {
  fetches.push(String(path));
  if (path === '/api/current') {
    const body = JSON.parse(options.body);
    return Promise.resolve(response({current_track_id: body.track_id}));
  }
  if (path === '/api/tracks/a') return detailA.promise.then(payload => response(payload));
  if (String(path).startsWith('/api/candidates?control=tempo%3Aoff%3A1&control=harmony%3Aoff%3A1&control=energy%3Aoff%3A1&control=genre%3Aoff%3A1&control=mood%3Aoff%3A1')) return candidatesA.promise.then(payload => response(payload));
  if (path === '/api/tracks/b') return Promise.resolve(response({handle:'b', display_label:'Bee', latest_run_status:'completed', available_locations:1, reasons:[], fields:{}}));
  return Promise.resolve(response({candidates:[{track_id:'cand-b', tier:'strong', score:0.8}]}));
};
function element(tag){return {tag, textContent:'', className:'', dataset:{}, style:{}, children:[], setAttribute(){}, append(...nodes){this.children.push(...nodes);}, replaceChildren(...nodes){this.children = nodes;}};}
const detail = element('section'), candidates = element('ol');
const rows = ['a','b'].map(id => ({dataset:{trackId:id}, className:''}));
context.document = {createElement: element, querySelector(){return null;}, querySelectorAll(selector){assert.strictEqual(selector, '#tracks li[data-track-id]'); return rows;}, getElementById(id){return id === 'detail' ? detail : id === 'candidates' ? candidates : null;}};
const graphCalls = [];
const graph = {nodeVal(fn){this.value = fn; return this;}, refresh(){this.refreshed = (this.refreshed || 0) + 1; return this;}, graphData(data){graphCalls.push(data); return {nodes:[]};}};
context.graph = graph;
vm.runInContext("state={current_track_id:null}; graphModel={nodes:[{id:'a',label:'A',moodScore:null},{id:'b',label:'B',moodScore:null}],links:[],unpositioned:[],selectedMood:'calm',colorRanges:{}}; visibleGraph={nodes:graphModel.nodes,links:[],unpositioned:[]}; forceGraph=graph;", context);
const first = context.setCurrent('a');
await Promise.resolve();
const second = context.setCurrent('b');
await second;
detailA.resolve({handle:'a', display_label:'A stale', latest_run_status:'completed', available_locations:1, reasons:[], fields:{}});
candidatesA.resolve({candidates:[{track_id:'cand-a', tier:'stale', score:0.1}]});
await first;
assert.deepStrictEqual(fetches.filter(u => u === '/api/tracks?limit=all' || u.startsWith('/api/mood-axis-graph')), []);
assert(fetches.includes('/api/current'));
assert(fetches.includes('/api/tracks/a'));
assert(fetches.includes('/api/tracks/b'));
assert.strictEqual(graphCalls.length, 0, 'selection-only changes must not replace forceGraph.graphData');
assert.strictEqual(graph.value({id:'b'}), 4);
assert.strictEqual(graph.value({id:'a'}), 1);
assert.deepStrictEqual(rows.map(r => r.className), ['', 'current']);
assert(detail.children[0].textContent === 'Bee', 'stale first detail must not overwrite latest selection');
assert(candidates.children[0].textContent.includes('cand-b'), 'stale first candidates must not overwrite latest selection');
assert(graph.refreshed >= 2, 'selected node styling is refreshed locally');
})().catch(error => { console.error(error); process.exit(1); });
""";
        subprocess.run(['node', '-e', script, str(APP_JS)], check=True, cwd=REPO_ROOT)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for refresh race tests')
    def test_stale_full_refresh_does_not_overwrite_newer_selection_refresh(self):
        script = r"""
const assert = require('assert');
const fs = require('fs'), vm = require('vm');
const context = {module:{exports:{}}, console, URLSearchParams, requestAnimationFrame(){}};
(async () => {
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
function deferred(){let resolve; const promise = new Promise(r => {resolve = r;}); return {promise, resolve};}
function response(payload){return {ok:true, json:async()=>payload};}
function point(id){return {id, label:id.toUpperCase(), title:id, artist:'Artist', x:{raw:0, normalized:0.5, scale:'native', label:'valence'}, y:{raw:0, normalized:0.5, scale:'native', label:'arousal'}, z:{raw:120, normalized:0.5, scale:'raw', label:'BPM'}, mood_score:{label:'calm', raw:0.5, normalized:0.5}, genres:[]};}
const refreshState = deferred(), refreshList = deferred(), refreshGraph = deferred();
const detailA = deferred(), candidatesA = deferred();
const fetches = [];
context.fetch = (path, options={}) => {
  fetches.push(String(path));
  if (path === '/api/state') return refreshState.promise.then(payload => response(payload));
  if (path === '/api/tracks?limit=all') return refreshList.promise.then(payload => response(payload));
  if (path === '/api/mood-axis-graph') return refreshGraph.promise.then(payload => response(payload));
  if (path === '/api/current') return Promise.resolve(response({current_track_id:'b'}));
  if (path === '/api/tracks/b') return Promise.resolve(response({handle:'b', display_label:'Bee', latest_run_status:'completed', available_locations:1, reasons:[], fields:{}}));
  if (path === '/api/tracks/a') return detailA.promise.then(payload => response(payload));
  if (String(path).startsWith('/api/candidates?control=tempo%3Aoff%3A1&control=harmony%3Aoff%3A1&control=energy%3Aoff%3A1&control=genre%3Aoff%3A1&control=mood%3Aoff%3A1')) return candidatesA.promise.then(payload => response(payload));
  return Promise.resolve(response({candidates:[{track_id:'cand-b', tier:'strong', score:0.8}]}));
};
function element(tag){return {tag, id:'', textContent:'', className:'', dataset:{}, style:{}, children:[], clientWidth:800, clientHeight:600, getContext(){return {clearRect(){}, fillRect(){}, beginPath(){}, moveTo(){}, lineTo(){}, stroke(){}, arc(){}, fill(){}};}, setAttribute(){}, append(...nodes){this.children.push(...nodes);}, replaceChildren(...nodes){this.children = nodes;}, replaceWith(){}};}
const elements = {tracks: element('ul'), detail: element('section'), candidates: element('ol'), 'mood-strip': element('canvas'), 'mood-strip-picker': element('input'), 'mood-strip-value': element('output'), 'selected-mood': element('select'), 'genre-filter': element('select'), 'graph-info': element('p')};
context.document = {createElement: element, createTextNode(value){return {textContent:String(value)};}, querySelector(){return null;}, querySelectorAll(selector){assert.strictEqual(selector, '#tracks li[data-track-id]'); return elements.tracks.children;}, getElementById(id){return elements[id] || null;}};
const rendered = [];
context.renderMap = data => rendered.push(data.nodes.map(n => n.id));
vm.runInContext('renderMap = globalThis.renderMap', context);
const stale = context.refresh();
refreshState.resolve({current_track_id:'a'});
refreshList.resolve({tracks:[{handle:'a', display_label:'Aye'}]});
await Promise.resolve();
const latest = context.setCurrent('b');
await latest;
refreshGraph.resolve({positioned:[point('a')], edges:[], selected_mood:'calm', available_moods:['calm']});
detailA.resolve({handle:'a', display_label:'A stale', latest_run_status:'completed', available_locations:1, reasons:[], fields:{}});
candidatesA.resolve({candidates:[{track_id:'cand-a', tier:'stale', score:0.1}]});
await stale;
assert.strictEqual(context.state.current_track_id, 'b', 'stale refresh state must not overwrite newer selection state');
assert.deepStrictEqual(elements.tracks.children.map(row => row.dataset.trackId), [], 'stale refresh must not render stale track list');
assert.deepStrictEqual(rendered, [], 'stale refresh must not render stale graph data');
assert(detail.children[0].textContent === 'Bee', 'stale refresh detail must not overwrite latest selection detail');
assert(candidates.children[0].textContent.includes('cand-b'), 'stale refresh candidates must not overwrite latest selection candidates');
assert(fetches.includes('/api/tracks?limit=all'));
})().catch(error => { console.error(error); process.exit(1); });
""";
        subprocess.run(['node', '-e', script, str(APP_JS)], check=True, cwd=REPO_ROOT)


    @unittest.skipUnless(shutil.which('node'), 'Node is required for same-selection detail race tests')
    def test_older_selection_detail_cannot_overwrite_newer_full_refresh_for_same_selection(self):
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
const olderDetail = deferred(), olderCandidates = deferred();
let trackDetailRequests = 0, candidateRequests = 0;
const fetches = [];
context.fetch = (path, options={}) => {
  fetches.push(String(path));
  if (path === '/api/current') return Promise.resolve(response({current_track_id:'a'}));
  if (path === '/api/state') return Promise.resolve(response({current_track_id:'a'}));
  if (path === '/api/tracks?limit=all') return Promise.resolve(response({tracks:[{handle:'a', display_label:'Aye'}]}));
  if (path === '/api/mood-axis-graph') return Promise.resolve(response({positioned:[point('a')], edges:[], selected_mood:'calm', available_moods:['calm']}));
  if (path === '/api/tracks/a') {
    trackDetailRequests += 1;
    return trackDetailRequests === 1
      ? olderDetail.promise.then(payload => response(payload))
      : Promise.resolve(response({handle:'a', display_label:'Fresh detail', latest_run_status:'completed', available_locations:1, reasons:[], fields:{}}));
  }
  if (String(path).startsWith('/api/candidates?control=tempo%3Aoff%3A1&control=harmony%3Aoff%3A1&control=energy%3Aoff%3A1&control=genre%3Aoff%3A1&control=mood%3Aoff%3A1')) {
    candidateRequests += 1;
    return candidateRequests === 1
      ? olderCandidates.promise.then(payload => response(payload))
      : Promise.resolve(response({candidates:[{track_id:'fresh-candidate', tier:'strong', score:0.9}]}));
  }
  return Promise.reject(new Error('unexpected fetch '+path));
};
function element(tag){return {tag, id:'', textContent:'', className:'', dataset:{}, style:{}, children:[], clientWidth:800, clientHeight:600, value:'', options:[], getContext(){return {clearRect(){}, fillRect(){}, beginPath(){}, moveTo(){}, lineTo(){}, stroke(){}, arc(){}, fill(){}};}, setAttribute(){}, append(...nodes){this.children.push(...nodes);}, replaceChildren(...nodes){this.children = nodes;}, replaceWith(){}};}
const elements = {tracks: element('ul'), detail: element('section'), candidates: element('ol'), 'mood-strip': element('canvas'), 'mood-strip-picker': element('input'), 'mood-strip-value': element('output'), 'selected-mood': element('select'), 'genre-filter': element('select'), 'graph-info': element('p')};
context.document = {createElement: element, createTextNode(value){return {textContent:String(value)};}, querySelector(){return null;}, querySelectorAll(selector){assert.strictEqual(selector, '#tracks li[data-track-id]'); return elements.tracks.children;}, getElementById(id){return elements[id] || null;}};
vm.runInContext("state={current_track_id:'a'}; selectionEpoch=1; graphModel={nodes:[{id:'a',moodScore:null}],links:[],unpositioned:[],selectedMood:'',colorRanges:{}}; visibleGraph={nodes:graphModel.nodes,links:[],unpositioned:[]};", context);
const olderRefresh = context.refresh();
await Promise.resolve();
assert.strictEqual(vm.runInContext('state.current_track_id', context), 'a', 'older refresh observed the selected track while detail is pending');
const newerRefresh = context.refresh();
await newerRefresh;
assert.strictEqual(elements.detail.children[0].textContent, 'Fresh detail', 'newer full refresh renders current detail first');
assert(elements.candidates.children[0].textContent.includes('fresh-candidate'), 'newer full refresh renders current candidates first');
olderDetail.resolve({handle:'a', display_label:'Stale delayed detail', latest_run_status:'completed', available_locations:1, reasons:[], fields:{}});
olderCandidates.resolve({candidates:[{track_id:'stale-candidate', tier:'stale', score:0.1}]});
await olderRefresh;
assert.strictEqual(vm.runInContext('state.current_track_id', context), 'a');
assert.strictEqual(elements.detail.children[0].textContent, 'Fresh detail', 'older delayed detail for same selected id must not overwrite newer refresh detail');
assert(elements.candidates.children[0].textContent.includes('fresh-candidate'), 'older delayed candidates for same selected id must not overwrite newer refresh candidates');
assert.strictEqual(trackDetailRequests, 2);
assert.strictEqual(candidateRequests, 2);
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
  if (path === '/api/state') return Promise.resolve(response({current_track_id:'a'}));
  if (path === '/api/tracks?limit=all') return Promise.resolve(response({tracks:[{handle:'a', display_label:'Aye'},{handle:'b', display_label:'Bee'}]}));
  if (path === '/api/mood-axis-graph') return Promise.resolve(response({positioned:[point('a'), point('b')], edges:[], selected_mood:'calm', available_moods:['calm']}));
  if (path === '/api/tracks/b') return Promise.resolve(response({handle:'b', display_label:'Bee', latest_run_status:'completed', available_locations:1, reasons:[], fields:{}}));
  if (path === '/api/tracks/a') return Promise.resolve(response({handle:'a', display_label:'A stale', latest_run_status:'completed', available_locations:1, reasons:[], fields:{}}));
  if (String(path).startsWith('/api/candidates?control=tempo%3Aoff%3A1&control=harmony%3Aoff%3A1&control=energy%3Aoff%3A1&control=genre%3Aoff%3A1&control=mood%3Aoff%3A1')) {
    const current = String(path).includes('current=b') ? 'cand-b' : 'cand-a';
    return Promise.resolve(response({candidates:[{track_id:current, tier:'strong', score:0.8}]}));
  }
  return Promise.reject(new Error('unexpected fetch '+path));
};
function element(tag){return {tag, id:'', textContent:'', className:'', dataset:{}, style:{}, children:[], clientWidth:800, clientHeight:600, getContext(){return {clearRect(){}, fillRect(){}, beginPath(){}, moveTo(){}, lineTo(){}, stroke(){}, arc(){}, fill(){}};}, setAttribute(){}, append(...nodes){this.children.push(...nodes);}, replaceChildren(...nodes){this.children = nodes;}, replaceWith(){}};}
const elements = {tracks: element('ul'), detail: element('section'), candidates: element('ol'), 'mood-strip': element('canvas'), 'mood-strip-picker': element('input'), 'mood-strip-value': element('output'), 'selected-mood': element('select'), 'genre-filter': element('select'), 'graph-info': element('p')};
context.document = {createElement: element, createTextNode(value){return {textContent:String(value)};}, querySelector(){return null;}, querySelectorAll(selector){assert.strictEqual(selector, '#tracks li[data-track-id]'); return elements.tracks.children;}, getElementById(id){return elements[id] || null;}};
const rendered = [];
context.renderMap = data => rendered.push(data.nodes.map(n => n.id));
vm.runInContext('renderMap = globalThis.renderMap', context);
const click = context.setCurrent('b');
await Promise.resolve();
const staleRefresh = context.refresh();
await staleRefresh;
assert.strictEqual(vm.runInContext('state.current_track_id', context), 'b', 'refresh must preserve optimistic latest click while POST is pending');
assert.deepStrictEqual(elements.tracks.children.map(row => row.className), ['', 'current']);
postCurrent.resolve();
await click;
assert.strictEqual(vm.runInContext('state.current_track_id', context), 'b', 'POST response should remain latest selected track despite intervening refresh');
assert(elements.detail.children[0].textContent === 'Bee', 'latest click detail must render after POST resolves');
assert(elements.candidates.children[0].textContent.includes('cand-b'), 'latest click candidates must render after POST resolves');
assert(fetches.includes('/api/state') && fetches.includes('/api/current'));
})().catch(error => { console.error(error); process.exit(1); });
""";
        subprocess.run(['node', '-e', script, str(APP_JS)], check=True, cwd=REPO_ROOT)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for history race tests')
    def test_late_history_response_does_not_overwrite_later_click_selection(self):
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
const resetPost = deferred();
const clickPost = deferred();
const stateFetch = deferred();
const fetches = [];
context.fetch = (path, options={}) => {
  fetches.push(String(path));
  if (path === '/api/reset') return resetPost.promise.then(() => response({current_track_id:null}));
  if (path === '/api/current') return clickPost.promise.then(() => response({current_track_id:'b'}));
  if (path === '/api/state') return stateFetch.promise.then(() => response({current_track_id:'b'}));
  if (path === '/api/tracks?limit=all') return Promise.resolve(response({tracks:[{handle:'a', display_label:'Aye'},{handle:'b', display_label:'Bee'}]}));
  if (path === '/api/mood-axis-graph') return Promise.resolve(response({positioned:[point('a'), point('b')], edges:[], selected_mood:'calm', available_moods:['calm']}));
  if (path === '/api/tracks/b') return Promise.resolve(response({handle:'b', display_label:'Bee', latest_run_status:'completed', available_locations:1, reasons:[], fields:{}}));
  if (String(path).startsWith('/api/candidates?')) return Promise.resolve(response({candidates:[{track_id:'cand-b', tier:'strong', score:0.8}]}));
  return Promise.reject(new Error('unexpected fetch '+path));
};
function element(tag){return {tag, id:'', textContent:'', className:'', dataset:{}, style:{}, children:[], clientWidth:800, clientHeight:600, value:'', options:[], getContext(){return {clearRect(){}, fillRect(){}, beginPath(){}, moveTo(){}, lineTo(){}, stroke(){}, arc(){}, fill(){}};}, setAttribute(){}, append(...nodes){this.children.push(...nodes);}, replaceChildren(...nodes){this.children = nodes;}, replaceWith(){}};}
const elements = {tracks: element('ul'), detail: element('section'), candidates: element('ol'), 'mood-strip': element('canvas'), 'mood-strip-picker': element('input'), 'mood-strip-value': element('output'), 'selected-mood': element('select'), 'genre-filter': element('select'), 'graph-info': element('p'), controls: element('div'), undo: element('button'), reset: element('button')};
context.document = {createElement: element, createTextNode(value){return {textContent:String(value)};}, querySelector(){return null;}, querySelectorAll(selector){assert.strictEqual(selector, '#tracks li[data-track-id]'); return elements.tracks.children;}, getElementById(id){return elements[id] || null;}};
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
assert(elements.detail.children[0].textContent === 'Bee', 'latest click detail remains rendered after stale reset response');
assert(elements.candidates.children[0].textContent.includes('cand-b'), 'latest click candidates remain rendered after stale reset response');
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
  if (path === '/api/tracks?limit=all') return Promise.resolve(response({tracks:[{handle:'a', display_label:'Aye'},{handle:'b', display_label:'Bee'}]}));
  if (path === '/api/mood-axis-graph') return Promise.resolve(response({positioned:[point('a'), point('b')], edges:[], selected_mood:'calm', available_moods:['calm']}));
  if (path === '/api/tracks/b') return Promise.resolve(response({handle:'b', display_label:'Bee stale', latest_run_status:'completed', available_locations:1, reasons:[], fields:{}}));
  if (String(path).startsWith('/api/candidates?')) return Promise.resolve(response({candidates:[{track_id:'cand-b', tier:'stale', score:0.8}]}));
  return Promise.reject(new Error('unexpected fetch '+path));
};
function element(tag){return {tag, id:'', textContent:'', className:'', dataset:{}, style:{}, children:[], clientWidth:800, clientHeight:600, value:'', options:[], getContext(){return {clearRect(){}, fillRect(){}, beginPath(){}, moveTo(){}, lineTo(){}, stroke(){}, arc(){}, fill(){}};}, setAttribute(){}, append(...nodes){this.children.push(...nodes);}, replaceChildren(...nodes){this.children = nodes;}, replaceWith(){}};}
const elements = {tracks: element('ul'), detail: element('section'), candidates: element('ol'), 'mood-strip': element('canvas'), 'mood-strip-picker': element('input'), 'mood-strip-value': element('output'), 'selected-mood': element('select'), 'genre-filter': element('select'), 'graph-info': element('p'), controls: element('div'), undo: element('button'), reset: element('button')};
context.document = {createElement: element, createTextNode(value){return {textContent:String(value)};}, querySelector(){return null;}, querySelectorAll(selector){assert.strictEqual(selector, '#tracks li[data-track-id]'); return elements.tracks.children;}, getElementById(id){return elements[id] || null;}};
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
context.document = {createElement: element, getElementById(id){assert.strictEqual(id, 'detail'); return detail;}};
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
assert(detail.children[2].textContent.startsWith('Selected mood score:'), 'selected score stays near title');
let rendered = nodes().map(n => n.textContent).join(' ');
assert(rendered.includes('Status: failed') && rendered.includes('evidence pending'));
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


if __name__ == '__main__':
    unittest.main()
