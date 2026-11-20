import json
import shutil
import tempfile
import unittest
from pathlib import Path

from music_analyzer.frameworks.explorer.server import create_server


from tests.support.node_script import run_node_script
from tests.support.explorer_app_bundle import explorer_app_script

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_JS = explorer_app_script(REPO_ROOT / 'music_analyzer' / 'frameworks' / 'explorer' / 'assets' / 'app.js')


from tests.support.three_track_graph_db import create_three_track_graph_db


M3U_DOWNLOAD_INTERACTION = """  bpmMin.value = '120'; bpmMax.value = '128'; count.value = '10';
  await button.onclick();
  const playlistRequests = requests.filter(path => path.includes('m3u'));
  assert.deepStrictEqual(playlistRequests, ['/api/playlists/m3u?start=track-start&bpm_min=120&bpm_max=128&count=10&min_key_strength=0.5'], 'Download M3U click must send selected start, BPM range, and requested count exactly once');"""
M3U_DOWNLOAD_SCRIPT = r"""
const assert = require('assert');
const app = require(process.argv[1]);
const assetSource = require('fs').readFileSync(process.argv[1], 'utf8');
assert(assetSource.includes('download-m3u'), 'browser asset must implement an explicit Download M3U control; current graph load behavior correctly avoids auto-fetch but offers no playlist action');
function makeElement(tag){
  const classes = new Set();
  return {tagName: tag.toUpperCase(), children: [], parentElement: null, attributes: {}, dataset: {}, style: {}, id: '', hidden: false, value: '', selectedOptions: [], textContent: '', onclick: null, onchange: null, type: '', name: '', className: '', clientWidth: 900, clientHeight: 700, width: 0, height: 0,
    classList: {add: c => classes.add(c), remove: c => classes.delete(c), contains: c => classes.has(c)},
    append(...nodes){for (const node of nodes) { if (node && typeof node === 'object') node.parentElement = this; this.children.push(node); }},
    replaceChildren(...nodes){this.children = []; this.append(...nodes);},
    replaceWith(node){const parent = this.parentElement; if (parent) parent.children = parent.children.map(child => child === this ? node : child); if (node && typeof node === 'object') node.parentElement = parent;},
    setAttribute(name, value){this.attributes[name] = String(value); if(name === 'id') this.id = String(value);},
    removeAttribute(name){delete this.attributes[name];},
    querySelector(selector){return find(this, selector);},
    getContext(){return {clearRect(){}, fillRect(){}, beginPath(){}, arc(){}, fill(){}, stroke(){}, moveTo(){}, lineTo(){}, set fillStyle(_v){}, set strokeStyle(_v){}};}
  };
}
function find(root, selector){
  const wantedId = selector.startsWith('#') ? selector.slice(1) : null;
  const wantedTag = wantedId ? null : selector.toUpperCase();
  const stack = [...(root.children || [])];
  while(stack.length){
    const node = stack.shift();
    if(!node || typeof node !== 'object') continue;
    if((wantedId && node.id === wantedId) || (wantedTag && node.tagName === wantedTag)) return node;
    stack.unshift(...(node.children || []));
  }
  return null;
}
function response(payload){return {ok:true, json:async()=>payload, text:async()=>JSON.stringify(payload)};}
const elements = {};
for (const id of ['library-loading','loading-status','loading-error','loading-retry','tracks','detail','map','controls','graph-load-status','track-search','selected-mood','genre-filter','mood-strip','mood-strip-picker','mood-strip-value']) { elements[id] = makeElement(id === 'map' || id === 'mood-strip' ? 'canvas' : id === 'track-search' ? 'input' : 'div'); elements[id].id = id; }
elements.map.parentElement = makeElement('div');
global.document = {createElement: makeElement, createTextNode: text => ({textContent: String(text)}), getElementById: id => elements[id] || null, querySelectorAll: () => []};
const frames = [];
global.requestAnimationFrame = cb => frames.push(cb);
function runFrames(){while(frames.length) frames.shift()();}
const graph = {dto_version:'mood-axis-graph-compact-v1', selected_mood:'relaxing', available_moods:['relaxing'], metadata:{graph_status:{state:'ready'}}, nodes:[
  {id:'track-start', label:'Start Track', x:{raw:0.4, normalized:0.4, scale:'native'}, y:{raw:0.5, normalized:0.5, scale:'native'}, z:{label:'BPM', raw:124, normalized:6.2, scale:'fixed'}, mood_score:{label:'relaxing',raw:0.8}, bpm:124, genres:[], reasons:[]},
  {id:'track-neighbor', label:'Neighbor Track', x:{raw:0.5, normalized:0.5, scale:'native'}, y:{raw:0.6, normalized:0.6, scale:'native'}, z:{label:'BPM', raw:126, normalized:6.3, scale:'fixed'}, mood_score:{label:'relaxing',raw:0.7}, bpm:126, genres:[], reasons:[]}
], edges:[{a:'track-start', b:'track-neighbor', score:0.91, explanation:'synthetic'}], unpositioned:[]};
const requests = [];
global.fetch = async path => {
  requests.push(String(path));
  if (String(path).startsWith('/api/mood-axis-graph')) return response(graph);
  if (String(path).startsWith('/api/playlists/m3u')) return {ok:true, text:async()=> '#EXTM3U\n/safe/track.flac\n', json:async()=>({})};
  if (path === '/api/state') return response({current_track_id:'track-start', history:[]});
  if (String(path).startsWith('/api/tracks/summary')) return response({tracks:[{handle:'track-start', title:'Start Track', artist:'Synthetic'}]});
  if (path === '/api/tracks/track-start') return response({handle:'track-start', metadata:{common:[['title','Start Track']], tags:[]}, fields:{bpm:{effective:124}}});
  throw new Error('unexpected fetch '+path);
};
(async () => {
  app.setStateForTesting({current_track_id:'track-start'});
  app.renderGraphLoadStatus();
  assert(!requests.some(path => path.includes('m3u')), 'rendering graph controls must not auto-fetch a playlist');
  // loadGraph awaits several frames; with nothing else pending, Node would
  // otherwise exit 0 silently before any assertion below runs.
  let loaded = false;
  const loading = app.loadGraph().then(() => { loaded = true; });
  for (let i = 0; i < 200 && !loaded; i++) { runFrames(); await new Promise(resolve => setImmediate(resolve)); }
  assert(loaded, 'loadGraph must settle');
  await loading;
  assert(!requests.some(path => path.includes('m3u')), 'loading/rendering the graph must not auto-fetch a playlist');
  function textOf(node){return String(node.textContent || '') + (node.children || []).map(textOf).join(' ');}
  const panelText = textOf(elements['graph-load-status']);
  const button = elements['graph-load-status'].querySelector('#download-m3u');
  assert(button, 'Explorer graph controls must expose a Download M3U button after graph load; it must be explicit user-click only, not an automatic fetch');
  assert(/Download\s+M3U/.test(panelText), 'the explicit playlist control must be labelled Download M3U');
  const bpmMin = elements['graph-load-status'].querySelector('#m3u-bpm-min');
  const bpmMax = elements['graph-load-status'].querySelector('#m3u-bpm-max');
  const count = elements['graph-load-status'].querySelector('#m3u-count');
  assert(bpmMin && bpmMax && count, 'M3U controls must expose bounded BPM and playlist length inputs');
  bpmMin.value = '120'; bpmMax.value = '128'; count.value = '10';
  await button.onclick();
  const playlistRequests = requests.filter(path => path.includes('m3u'));
  assert.deepStrictEqual(playlistRequests, ['/api/playlists/m3u?start=track-start&bpm_min=120&bpm_max=128&count=10&min_key_strength=0.5'], 'Download M3U click must send selected start, BPM range, and requested count exactly once');
})().then(() => console.log('NODE_SCRIPT_COMPLETED')).catch(error => { console.error(error); process.exit(1); });
"""


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

    def test_static_html_does_not_instruct_manual_graph_loading_in_both_mirrored_assets(self):
        for package in ('music_analyzer', 'music_explorer'):
            with self.subTest(package=package):
                html = (REPO_ROOT / package / 'frameworks/explorer/assets/index.html').read_text(encoding='utf-8')
                self.assertNotIn('initial graph shows the whole library', html)
                self.assertNotIn('Use Load graph', html, 'startup loads the graph without a manual step')

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
context.renderTracks([{handle:'client-click', display_label:'Client Click'},{handle:'server-current', display_label:'Server Current'}]); // retained prior search results
await context.setCurrent('client-click');
assert.strictEqual(vm.runInContext('state.current_track_id', context), 'server-current', 'rejected POST restores authoritative server selection');
await context.refresh();
assert.strictEqual(vm.runInContext('state.current_track_id', context), 'server-current', 'refresh after rejection must not overlay the rejected click intent');
assert.deepStrictEqual(elements.tracks.children[0].children[2].children.map(row => row.className), ['', 'current']);
assert(elements.detail.children.some(child => child.textContent.includes('Current Track')), 'detail follows authoritative server selection after refresh');
assert(!fetches.some(path => path.startsWith('/api/candidates')), 'refresh does not request removed candidate list');
assert(!fetches.some(path => path.startsWith('/api/tracks/summary')), 'refresh preserves existing search rows');
assert(fetches.includes('/api/current') && fetches.includes('/api/state'));
})().then(() => console.log('NODE_SCRIPT_COMPLETED')).catch(error => { console.error(error); process.exit(1); });
"""
        run_node_script(self, script, str(APP_JS))


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
})().then(() => console.log('NODE_SCRIPT_COMPLETED')).catch(error => { console.error(error); process.exit(1); });
""";
        run_node_script(self, script, str(APP_JS))

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
const refreshState = deferred();
const detailA = deferred();
const fetches = [];
context.fetch = (path, options={}) => {
  fetches.push(String(path));
  if (path === '/api/state') return refreshState.promise.then(payload => response(payload));
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
await waitForFetch('/api/tracks/a');
assert(fetches.includes('/api/tracks/a'), 'stale refresh reached selected detail request');
const latest = context.setCurrent('b');
await latest;
detailA.resolve({handle:'a', display_label:'A stale', latest_run_status:'completed', available_locations:1, reasons:[], fields:{}});
await stale;
assert.strictEqual(vm.runInContext('state.current_track_id', context), 'b', 'stale refresh state must not overwrite newer selection state');
assert.deepStrictEqual(elements.tracks.children.map(row => row.dataset.trackId), [], 'stale refresh must not render stale track list');
assert.deepStrictEqual(rendered, [], 'stale refresh must not render stale graph data');
assert(elements.detail.children.some(child => child.textContent.includes('Current Track')), 'stale refresh detail must not overwrite latest selection detail');
assert(!fetches.some(path => path.startsWith('/api/candidates')), 'selection does not request removed candidate list');
assert(!fetches.some(path => path.startsWith('/api/tracks/summary')), 'refresh never refills sidebar');
})().then(() => console.log('NODE_SCRIPT_COMPLETED')).catch(error => { console.error(error); process.exit(1); });
""";
        run_node_script(self, script, str(APP_JS))


    def test_undo_and_reset_still_force_complete_ui_refresh(self):
        app = APP_JS.read_text()
        self.assertIn('async function applyHistorySelection(action){if(await trackSelection.rewind(action)) await refresh();}', app)
        use_case = (REPO_ROOT / 'music_explorer/frameworks/explorer/assets/app/application/select-track/select-track.js').read_text()
        history = use_case[use_case.index('async function rewind(action) {'):use_case.index('function loadDetail(generation) {')]
        boundaries = (
            'const generation = ++latestGeneration;',
            'const accepted = await explorerApi.applyHistory(action);',
            'if (generation !== latestGeneration) return false;',
            'accept(accepted);',
            'return true;',
        )
        previous = -1
        for boundary in boundaries:
            self.assertIn(boundary, history)
            current = history.index(boundary)
            self.assertGreater(current, previous, 'history must guard stale responses before epoch sync and refresh')
            previous = current
        self.assertIn('explorerApi.chooseCurrentTrack({trackId, selectionToken, selectionEpoch: epoch,', use_case)
        self.assertIn("document.getElementById('undo').onclick=()=>applyHistorySelection('undo');", app)
        self.assertIn("document.getElementById('reset').onclick=()=>applyHistorySelection('reset');", app)

    def test_detail_dials_are_half_size_and_have_no_tick_styles(self):
        style = (REPO_ROOT / 'music_analyzer/frameworks/explorer/assets/style.css').read_text()
        self.assertIn('#detail .score-gauge{position:relative;width:39px;height:39px;', style)
        self.assertIn('@media(max-width:700px){#detail .score-gauge{width:34px;height:34px}', style)
        self.assertNotIn('.score-tick', style)

    def test_browser_startup_source_leaves_sidebar_empty_until_search(self):
        for app in (APP_JS, explorer_app_script(REPO_ROOT / 'music_explorer/frameworks/explorer/assets/app.js')):
            with self.subTest(app=app):
                source = app.read_text(encoding='utf-8')
                refresh_source = source[source.index('async function refresh()'):source.index('function loadTrackSummaryPage(')]
                self.assertNotIn("/api/tracks/summary", refresh_source)
                self.assertNotIn("/api/tracks?limit=all", refresh_source)
                self.assertNotIn("/api/mood-axis-graph", refresh_source, 'startup refresh must not request graph before user clicks Load graph')
                self.assertIn('renderGraphLoadStatus()', refresh_source)
                self.assertIn('function loadGraph(){return graphLoad.load();}', source)
                self.assertNotIn("button.id='load-graph'", source)
                self.assertNotIn("'Load graph'", source)
                self.assertIn('loadGraph', source[source.index('module.exports'):])
                self.assertIn('getStateForTesting', source[source.index('module.exports'):])

    @unittest.skipUnless(shutil.which('node'), 'Node is required for compact summary startup tests')
    def test_initial_refresh_leaves_search_empty_and_renders_selected_detail_without_graph(self):
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
  app.renderTracks([]); // boot now initializes search before refresh
  const refresh = app.refresh();
  runNextFrame();
  await refresh;
  assert(!fetches.some(path => path.startsWith('/api/tracks/summary')), 'initial sidebar stays empty until search');
  assert(!fetches.includes('/api/tracks?limit=all'), 'initial list must not use unbounded full track API');
  assert(!fetches.includes('/api/mood-axis-graph'), 'startup must not decide to trigger the graph for large libraries');
  const rows = elements.tracks.children[0].children[2].children;
  assert.deepStrictEqual(rows.map(row => row.dataset.trackId), [], 'selected detail does not populate sidebar');
  assert(elements.detail.children.some(child => child.textContent.includes('Current Track')), 'selected detail renders without graph data');
  assert.strictEqual(app.getStateForTesting().current_track_id, 'off-page');
  assert.deepStrictEqual(app.getStateForTesting().history, ['previous']);
  assert.strictEqual(elements['track-search'].oninput && typeof elements['track-search'].oninput, 'function', 'list search is usable without graph');
})().then(() => console.log('NODE_SCRIPT_COMPLETED')).catch(error => { console.error(error); process.exit(1); });
"""
        run_node_script(self, script, str(APP_JS))


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
  await waitFor(() => calls.length === 1, 'refresh should fetch only state after the first frame');
  assert.deepStrictEqual(calls, ['/api/state']);
  assert(!calls.includes('/api/mood-axis-graph'), 'refresh must not load graph before explicit user click');
  await promise;
  assert(elements['library-loading'].classList.contains('done'));
  assert.strictEqual(elements['library-loading'].attributes['aria-busy'], 'false');
})().then(() => console.log('NODE_SCRIPT_COMPLETED')).catch(error => { console.error(error); process.exit(1); });
"""
        run_node_script(self, script, str(APP_JS))

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
  pending[1].resolve(ok({current_track_id:null})); await second;
  assert(elements['library-loading'].classList.contains('done'), 'newest refresh may clear loading');
  const failing = app.refresh().catch(error => error);
  runNextFrame();
  await waitForPending(3);
  pending[2].reject(new Error('network down'));
  const error = await failing;
  assert.match(error.message, /network down/);
  assert.strictEqual(elements['library-loading'].attributes['aria-busy'], 'false');
  assert.match(elements['loading-status'].textContent, /Unable to load/);
  assert.strictEqual(elements['loading-retry'].hidden, false);
  assert.strictEqual(typeof elements['loading-retry'].onclick, 'function');
})().then(() => console.log('NODE_SCRIPT_COMPLETED')).catch(error => { console.error(error); process.exit(1); });
"""
        run_node_script(self, script, str(APP_JS))


    def test_mirrored_browser_assets_advertise_explicit_m3u_download_without_startup_fetch(self):
        for app in (APP_JS, explorer_app_script(REPO_ROOT / 'music_explorer/frameworks/explorer/assets/app.js')):
            with self.subTest(app=app):
                source = app.read_text(encoding='utf-8')
                self.assertIn('download-m3u', source, 'mirrored Explorer assets must expose an explicit Download M3U button')
                self.assertIn('/api/playlists/m3u', source, 'browser assets must call the M3U endpoint only from the explicit download action')
                startup_slice = source[source.index('async function refresh()'):source.index('function graphQueryFromControls()') if 'function graphQueryFromControls()' in source else source.index('function renderTracks')]
                self.assertNotIn('/api/playlists/m3u', startup_slice, 'initial refresh must not auto-fetch M3U playlists')


if __name__ == '__main__':
    unittest.main()
