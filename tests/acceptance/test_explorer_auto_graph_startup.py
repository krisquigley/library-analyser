"""Issue #70 PR3 RED contracts for automatic graph startup in both delivery assets.

Run the complete script without replacing any production function. Only DOM,
fetch and scheduling boundaries are fake. Small indexed-v3 responses exercise
real model construction and canvas rendering; this is not a WebGL or large
payload responsiveness measurement. Node absence fails rather than skipping.
"""
import os
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]
NODE = os.environ.get('EXPLORER_TEST_NODE') or shutil.which('node')
if not NODE and Path('/tmp/node-host-v24').is_file():
    NODE = '/tmp/node-host-v24'


HARNESS = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const draws=[];
const canvasContext={clearRect(){},fillRect(){},beginPath(){},fill(){},
  arc(...args){draws.push(args);}};
function element(tag){return {
  tagName:tag.toUpperCase(),id:'',children:[],attributes:{},dataset:{},style:{},
  value:'',textContent:'',hidden:false,disabled:false,className:'',
  clientWidth:800,clientHeight:600,
  append(...nodes){for(const n of nodes){n.parentElement=this;this.children.push(n);}},
  replaceChildren(...nodes){this.children=[];this.textContent='';this.append(...nodes);},
  setAttribute(k,v){this.attributes[k]=String(v);},
  getAttribute(k){return this.attributes[k]??null;},
  removeAttribute(k){delete this.attributes[k];},
  getBoundingClientRect(){return {width:800,height:600,left:0,top:0};},
  getContext(){return canvasContext;},
  querySelector(selector){return walk(this).find(n=>n!==this&&n.tagName===selector.toUpperCase())||null;},
  get innerText(){return [this.textContent,...this.children.filter(n=>!n.hidden).map(n=>n.innerText)].join(' ');},
};}
function walk(root){return [root,...root.children.flatMap(walk)];}
function deferred(){let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};}
function response(body){return {ok:true,json:async()=>body,text:async()=>String(body)};}
const roots={};
for(const id of ['tracks','track-search','undo','reset','controls','detail','graph-load-status',
                 'loading-surface','loading-status','loading-error','loading-retry','graph3d']){
  roots[id]=element(id==='track-search'?'input':'div');roots[id].id=id;
}
const graphDto={dto_version:'mood-axis-graph-indexed-v1',selected_mood:'calm',available_moods:['calm'],
  axis:[{key:'x',label:'Valence',scale:'unit'},{key:'y',label:'Arousal',scale:'unit'},
        {key:'z',label:'BPM',scale:'bpm'}],
  nodes:[['node-a','Graph fixture',0.2,0.2,0.3,0.3,120,0.4,null,0.6,[],[]]],
  links:[],unpositioned:[],genre_labels:[],reason_text:[],explanation_table:[],provenance_table:[],
  metadata:{graph_status:{state:'ready'}}};
let stateBody={current_track_id:null,selection_epoch:0};
let stateGate=null,detailGate=null,summaryGate=null;
const graphGate=deferred(),requests=[],timers=new Map();
let timerId=0,now=0;
const context=vm.createContext({console,URL,URLSearchParams,
  document:{createElement:element,createTextNode:t=>({...element('text'),textContent:String(t)}),
    getElementById(id){return roots[id]||Object.values(roots).flatMap(walk).find(n=>n.id===id)||null;},
    querySelectorAll(){return rows();}},
  requestAnimationFrame:fn=>{fn(now);return 1;},
  setTimeout:(fn,delay=0)=>{const id=++timerId;timers.set(id,{fn,at:now+delay});return id;},
  clearTimeout:id=>timers.delete(id),
  fetch:async(path,options)=>{
    const url=new URL(String(path),'http://example.test');requests.push({url,options});
    if(url.pathname==='/api/mood-axis-graph')return graphGate.promise;
    if(url.pathname==='/api/state')return stateGate?stateGate.promise:response(stateBody);
    if(url.pathname==='/api/tracks/summary')return summaryGate?summaryGate.promise:response({tracks:[],metadata:{track_count:0},next_cursor:null});
    if(url.pathname==='/api/undo'||url.pathname==='/api/reset')return response(stateBody);
    if(url.pathname.startsWith('/api/tracks/'))return detailGate?detailGate.promise:response({handle:stateBody.current_track_id,title:'Selected fixture',stages:[],metadata:{}});
    throw new Error('Unexpected request: '+path);
  },
});
function boot(){vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context,{filename:process.argv[1]});}
async function flush(){for(let i=0;i<60;i++)await Promise.resolve();}
async function advance(ms){now+=ms;for(const [id,t]of [...timers])if(t.at<=now){timers.delete(id);t.fn();}await flush();}
function rows(){return walk(roots.tracks).filter(n=>n.tagName==='TR'&&n.dataset.trackId);}
function graphRequests(){return requests.filter(r=>r.url.pathname==='/api/mood-axis-graph');}
function assertStartupGraph(){
  assert.equal(graphRequests().length,1,'startup must automatically start exactly one graph request without any click');
  assert.equal(graphRequests()[0].url.searchParams.get('contract'),'v3','automatic startup retains the indexed-v3 request contract');
}
function graphText(){return roots['graph-load-status'].innerText;}
function assertNoInitialList(){assert.equal(requests.filter(r=>['/api/tracks','/api/tracks/summary','/api/track-summaries'].includes(r.url.pathname)).length,0,'startup does not fill the sidebar');assert.equal(rows().length,0);}
function assertGraphRendered(){
  assert(draws.length>0,'successful automatic response must render a positioned node without a click');
  assert(draws.every(args=>args.every(Number.isFinite)),'rendered fixture uses finite canvas coordinates');
  assert(/graph ready/i.test(graphText()),'automatic success exposes ready feedback');
  assert(context.document.getElementById('download-m3u'),'automatic ready graph retains M3U controls');
}
"""


class GraphAutoloadStartupTests(unittest.TestCase):
    def run_browser(self, scenario):
        self.assertTrue(NODE, 'Node is required; configure EXPLORER_TEST_NODE')
        script = HARNESS + '\n(async()=>{\n' + scenario + '\n})().catch(e=>{console.error(e);process.exitCode=1;});'
        for package in ('music_analyzer', 'music_explorer'):
            with self.subTest(package=package):
                app = ROOT / package / 'frameworks/explorer/assets/app.js'
                result = subprocess.run([NODE, '-e', script, str(app)], cwd=ROOT,
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_startup_requests_one_v3_graph_without_search_or_click(self):
        self.run_browser(r"""
boot();await flush();assertNoInitialList();assertStartupGraph();
assert(/loading|rendering/i.test(graphText()),'automatic request has inline loading feedback');
assert(!walk(roots['graph-load-status']).some(n=>n.tagName==='BUTTON'&&/^load graph$/i.test(n.innerText.trim())),
  'startup no longer requires a manual Load graph action');
""")

    def test_graph_start_does_not_wait_for_pending_state_or_search(self):
        self.run_browser(r"""
stateGate=deferred();summaryGate=deferred();boot();await flush();assertNoInitialList();
assert(requests.some(r=>r.url.pathname==='/api/state'),'fixture state request really is pending');
roots['track-search'].value='Matching';roots['track-search'].oninput();await advance(150);
assert.equal(requests.filter(r=>r.url.pathname==='/api/tracks/summary').length,1,'fixture search really is pending');
assertStartupGraph();
graphGate.resolve(response(graphDto));await flush();assertGraphRendered();
assert.equal(rows().length,0,'graph completion does not fabricate search rows');
""")

    def test_graph_start_and_render_do_not_wait_for_selected_detail(self):
        self.run_browser(r"""
stateBody={current_track_id:'selected',selection_epoch:0};detailGate=deferred();
boot();await flush();
assert.equal(requests.filter(r=>r.url.pathname==='/api/tracks/selected').length,1,'fixture detail really is pending');
assertNoInitialList();assertStartupGraph();
graphGate.resolve(response(graphDto));await flush();assertGraphRendered();
assert.equal(requests.filter(r=>r.url.pathname.startsWith('/api/tracks/')&&r.url.pathname!=='/api/tracks/summary').length,1,
  'automatic graph must not fetch another track detail');
""")

    def test_successful_startup_graph_renders_without_user_interaction(self):
        self.run_browser(r"""
boot();await flush();assertStartupGraph();
graphGate.resolve(response(graphDto));await flush();assertGraphRendered();
assertNoInitialList();assert.equal(graphRequests().length,1,'rendering success does not start another request');
""")

    def test_refresh_undo_and_reset_do_not_duplicate_pending_startup_graph(self):
        self.run_browser(r"""
boot();await flush();assertStartupGraph();
await context.refresh();await roots.undo.onclick();await roots.reset.onclick();await flush();
assert(requests.filter(r=>r.url.pathname==='/api/state').length>1,'refresh exercised the state boundary');
for(const action of ['undo','reset'])assert(requests.some(r=>r.url.pathname==='/api/'+action&&r.options.method==='POST'),'history control exercised: '+action);
assert.equal(graphRequests().length,1,'refresh, undo and reset must not restart an in-flight automatic graph');
assertNoInitialList();graphGate.resolve(response(graphDto));await flush();assertGraphRendered();
""")

    def test_refresh_undo_and_reset_do_not_reload_ready_startup_graph(self):
        self.run_browser(r"""
boot();await flush();assertStartupGraph();graphGate.resolve(response(graphDto));await flush();assertGraphRendered();
await context.refresh();await roots.undo.onclick();await roots.reset.onclick();await flush();
assert(requests.filter(r=>r.url.pathname==='/api/state').length>1,'refresh exercised the state boundary');
for(const action of ['undo','reset'])assert(requests.some(r=>r.url.pathname==='/api/'+action&&r.options.method==='POST'),'history control exercised: '+action);
assert.equal(graphRequests().length,1,'refresh, undo and reset retain the successful graph rather than redownloading it');
assertNoInitialList();assertGraphRendered();
""")

    def test_baseline_control_existing_graph_path_renders_v3_fixture(self):
        """Positive control calls the existing loader, not a RED workaround."""
        self.run_browser(r"""
boot();await flush();assertNoInitialList();
if(!graphRequests().length){const manual=context.document.getElementById('load-graph');assert(manual,'baseline manual graph control exists');manual.onclick();}
await flush();assertStartupGraph();graphGate.resolve(response(graphDto));await flush();assertGraphRendered();
""")

    def test_ready_reload_control_requests_only_graph_and_preserves_m3u(self):
        self.run_browser(r"""
boot();await flush();assertStartupGraph();graphGate.resolve(response(graphDto));await flush();assertGraphRendered();
const reload=context.document.getElementById('reload-graph');
assert(reload&&reload.tagName==='BUTTON','ready graph preserves an explicit Reload graph control');
assert.equal(reload.innerText.trim(),'Reload graph');
const before=requests.length;reload.onclick();await flush();
assert.deepEqual(requests.slice(before).map(r=>r.url.pathname),['/api/mood-axis-graph'],
  'explicit ready reload requests graph only, not state, search, detail, or M3U');
assert.equal(graphRequests().length,2,'one explicit reload adds exactly one graph request');
assert.equal(graphRequests()[1].url.searchParams.get('contract'),'v3');
assertGraphRendered();assertNoInitialList();
assert(!walk(roots['graph-load-status']).some(n=>n.tagName==='BUTTON'&&/^load graph$/i.test(n.innerText.trim())),
  'ready reload does not reintroduce manual startup Load graph');
""")


if __name__ == '__main__':
    unittest.main()
