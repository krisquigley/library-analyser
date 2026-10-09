"""Issue70 PR3 graph/search independence contracts for both packaged scripts.

The complete delivery asset runs with fake browser I/O only. Baseline explicit-load
controls exercise the same graph fixture and canvas/detail adapters to distinguish
missing automatic startup REDs from broken fixtures. No private data or timing
claims; deferred responses cover request independence, not CPU responsiveness.
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
function element(tag) {
  return {
    tagName: tag.toUpperCase(), id:'', children:[], attributes:{}, dataset:{},
    className:'', value:'', textContent:'', hidden:false, disabled:false,
    getContext(){return canvasContext;},
    append(...nodes){this.children.push(...nodes);},
    replaceChildren(...nodes){this.children=[...nodes]; this.textContent='';},
    setAttribute(k,v){this.attributes[k]=String(v);},
    getAttribute(k){return this.attributes[k] ?? null;},
    removeAttribute(k){delete this.attributes[k];},
    querySelector(selector){return walk(this).find(n=>n!==this&&n.tagName===selector.toUpperCase())||null;},
    get innerText(){return [this.textContent,...this.children.filter(n=>!n.hidden).map(n=>n.innerText||n.textContent||'')].join(' ');},
  };
}
function walk(root){return [root,...root.children.flatMap(walk)];}
function deferred(){let resolve; const promise=new Promise(r=>resolve=r); return {promise,resolve};}
function response(body,ok=true){return {ok,json:async()=>body,text:async()=>String(body)};}
function page(tracks=[],next_cursor=null){return {tracks,next_cursor,metadata:{track_count:tracks.length}};}
const canvasPaints=[];
const canvasContext={clearRect(){},fillRect(){},beginPath(){},arc(...args){canvasPaints.push(args);},fill(){}};
const fixtureTrack={handle:'result',title:'Matching title',artist:'Artist'};
const roots={};
for(const id of ['tracks','track-search','undo','reset','controls','detail','graph-load-status',
                  'loading-surface','loading-status','loading-error','loading-retry']) {
  roots[id]=element(id==='track-search'?'input':id==='undo'||id==='reset'?'button':'div');
  roots[id].id=id;
}
// Match the actual page's initially visible blocking loading surface.
roots['loading-surface'].className='loading-surface';
roots['loading-surface'].setAttribute('aria-busy','true');
const search=roots['track-search'], tracks=roots.tracks;
let timerId=0, now=0;
const timers=new Map(), requests=[];
let stateBody={current_track_id:null,selection_epoch:0};
let stateGate=null;
const graphGate=deferred();
let graphResponder=()=>graphGate.promise;
let summaryResponder=()=>response(page([fixtureTrack]));
const context=vm.createContext({
  console,URLSearchParams,URL,
  document:{createElement:element,createTextNode:t=>({...element('text'),textContent:String(t)}),
    getElementById(id){return roots[id]||Object.values(roots).flatMap(walk).find(n=>n.id===id)||null;},
    querySelectorAll(){return walk(tracks).filter(n=>n.tagName==='TR'&&n.dataset.trackId);}},
  requestAnimationFrame:fn=>{fn(now);return 1;},
  setTimeout:(fn,delay=0)=>{const id=++timerId;timers.set(id,{fn,at:now+delay});return id;},
  clearTimeout:id=>timers.delete(id),
  fetch:async(path,options)=>{
    const url=new URL(String(path),'http://example.test');
    requests.push({url,options});
    if(url.pathname==='/api/mood-axis-graph') return graphResponder(url);
    if(url.pathname==='/api/state') return stateGate?stateGate.promise:response(stateBody);
    if(url.pathname==='/api/tracks/summary') return summaryResponder(url);
    if(url.pathname==='/api/undo'||url.pathname==='/api/reset') return response(stateBody);
    if(url.pathname==='/api/current') {
      stateBody={...stateBody,current_track_id:JSON.parse(options.body).track_id};
      return response(stateBody);
    }
    if(url.pathname.startsWith('/api/tracks/')) return response({handle:url.pathname.split('/').at(-1),fields:{},metadata:{common:[['title','Accepted result detail']],tags:[]}});
    throw new Error('Unexpected request: '+path);
  },
});
function boot(){vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context,{filename:process.argv[1]});}
async function flush(){for(let i=0;i<40;i++) await Promise.resolve();}
async function advance(ms){now+=ms;for(const [id,t] of [...timers])if(t.at<=now){timers.delete(id);t.fn();}await flush();}
function input(value){search.value=value;assert.equal(typeof search.oninput,'function','search must be wired before any summary response');search.oninput();}
function rows(){return walk(tracks).filter(n=>n.tagName==='TR'&&n.dataset.trackId);}
function summaryRequests(){return requests.filter(r=>r.url.pathname==='/api/tracks/summary');}
function visibleStatus(){return walk(tracks).filter(n=>!n.hidden&&['status','alert'].includes(n.getAttribute('role'))).map(n=>n.innerText).join(' ');}
function retryButton(){return walk(tracks).find(n=>n.tagName==='BUTTON'&&!n.hidden&&/retry/i.test(n.innerText));}
async function searchFor(value){input(value);await advance(150);}

// Public indexed v3 wire fixture: a positioned searched track with no edges.
const graphBody={dto_version:'mood-axis-graph-indexed-v1',selected_mood:'calm',
  available_moods:['calm'],axis:[{key:'x',label:'Valence',scale:'native'},
    {key:'y',label:'Arousal',scale:'native'},{key:'z',label:'Mood',scale:'native'}],
  nodes:[['result','Matching title',0.2,0.2,0.3,0.3,0.4,0.4,120,0.4,[],[]]],
  links:[],unpositioned:[],genre_labels:[],reason_text:[],explanation_table:[],
  provenance_table:[],metadata:{graph_status:{state:'ready'}}};
function graphRequests(){return requests.filter(r=>r.url.pathname==='/api/mood-axis-graph');}
function graphButtons(){return walk(roots['graph-load-status']).filter(n=>n.tagName==='BUTTON'&&!n.hidden);}
function graphStatus(){return roots['graph-load-status'].innerText;}
function graphRetry(){return graphButtons().find(n=>/retry/i.test(n.innerText));}
function assertInlineOnly(){
  const overlay=roots['loading-surface'];
  assert(overlay.hidden||!/(^|\s)(active|error)(\s|$)/.test(overlay.className),
    'graph loading/failure must not keep a blocking library overlay');
  assert.notEqual(overlay.getAttribute('aria-busy'),'true','graph must not own blocking library busy state');
  assert.equal(search.disabled,false,'search stays enabled');
}
async function start(mode='automatic'){
  boot(); await flush();
  if(mode==='baseline-control' && graphRequests().length===0){
    // Exercise the existing real loadGraph path on baseline; never replace it.
    // When startup becomes automatic, use that request instead so controls stay valid.
    context.loadGraph().catch(()=>{}); await flush();
  }
  assert.equal(graphRequests().length,1,'graph must start automatically without a manual click');
  assert.equal(graphRequests()[0].url.searchParams.get('contract'),'v3','preserve graph contract');
}
async function selectResult(){
  const button=rows()[0].children[0].children[0];
  const before=requests.length;
  await button.onclick(); await flush();
  assert.deepEqual(requests.slice(before).map(r=>r.url.pathname),['/api/current','/api/tracks/result'],
    'selection only posts intent and fetches accepted single-track detail, without graph refresh');
  assert.equal(button.getAttribute('aria-current'),'true');
  assert(roots.detail.innerText.includes('Accepted result detail'),
    'accepted metadata title is shown while graph is unrelated, not just selection/path fallback');
}
async function searchAndDetail(){
  await searchFor('Matching');
  assert.equal(rows().length,1,'search rows render independently');
  await selectResult(); assertInlineOnly();
}
async function assertGraphCompletionPreservesSidebar(){
  const beforeRows=rows()[0],beforeDetail=roots.detail.innerText;
  const summaries=summaryRequests().length,details=requests.filter(r=>r.url.pathname==='/api/tracks/result').length;
  graphGate.resolve(response(graphBody)); await flush();
  assert(/graph ready/i.test(graphStatus()),'graph becomes ready when its own response arrives');
  assert(canvasPaints.length>0,'real canvas adapter renders the positioned fixture, not just status text');
  assert.equal(rows()[0],beforeRows,'graph completion must not replace searched rows');
  assert.equal(search.value,'Matching');
  assert.equal(roots.detail.innerText,beforeDetail,'graph completion must not replace accepted detail');
  assert.equal(summaryRequests().length,summaries);
  assert.equal(requests.filter(r=>r.url.pathname==='/api/tracks/result').length,details);
  assertInlineOnly();
}

"""

PENDING_SCENARIO = r"""
await start(mode);
assertInlineOnly();
assert(/loading graph/i.test(graphStatus()),'pending graph has inline loading feedback');
await searchAndDetail();
assert.equal(graphRequests().length,1,'search/detail must not restart pending graph');
await assertGraphCompletionPreservesSidebar();
"""

FAILURE_RETRY_SCENARIO = r"""
await start(mode);
await searchAndDetail();
graphGate.resolve(response('graph temporarily unavailable',false)); await flush();
assert(/graph temporarily unavailable/i.test(graphStatus()),'failed graph has scoped error feedback');
assertInlineOnly();
// Search and selection must still work after failure, not only while pending.
await searchAndDetail();
const retry=graphRetry(); assert(retry,'automatic graph failure offers an inline Retry graph button');
const beforeRows=rows()[0],beforeDetail=roots.detail.innerText;
const retryGate=deferred(); graphResponder=()=>retryGate.promise;
const before=requests.length; retry.onclick(); await flush();
const retried=requests.slice(before);
assert.equal(retried.length,1,'graph retry must not refresh state, search, or detail');
assert.equal(retried[0].url.pathname,'/api/mood-axis-graph');
assert.equal(retried[0].url.searchParams.get('contract'),'v3');
assert(/loading graph/i.test(graphStatus()),'retry replaces error with inline loading');
assert(!graphRetry(),'pending retry must not retain a clickable duplicate retry');
assertInlineOnly();
retryGate.resolve(response(graphBody)); await flush();
assert(/graph ready/i.test(graphStatus()));
assert(!graphRetry(),'successful retry clears error/retry');
assert(canvasPaints.length>0,'retry success renders real graph fixture');
assert.equal(rows()[0],beforeRows); assert.equal(roots.detail.innerText,beforeDetail);
assertInlineOnly();
"""

SEARCH_FAILURE_SCENARIO = r"""
await start(mode);
summaryResponder=()=>response('search temporarily unavailable',false);
await searchFor('Matching');
assert(/search temporarily unavailable/i.test(visibleStatus()),'fixture establishes visible search failure');
assert.equal(rows().length,0);
const failedSearchStatus=visibleStatus(),before=requests.length;
graphGate.resolve(response(graphBody)); await flush();
assert(/graph ready/i.test(graphStatus()),'search failure must not prevent independent graph success');
assert(canvasPaints.length>0,'graph response actually renders despite failed search');
assert.equal(graphRequests().length,1,'search failure must not restart graph');
assert.equal(requests.length,before,'graph completion must not refetch failed search or state');
assert.equal(visibleStatus(),failedSearchStatus,'graph success must not erase scoped search failure');
assert(retryButton(),'search retry remains usable after graph success');
summaryResponder=()=>response(page([fixtureTrack])); retryButton().onclick(); await flush();
assert.equal(rows().length,1,'search retry remains independent of ready graph');
assert.equal(graphRequests().length,1);
assertInlineOnly();
"""


class ExplorerAutomaticGraphIndependenceTests(unittest.TestCase):
    def run_browser(self, scenario, mode='automatic'):
        self.assertTrue(NODE, 'Node is required; configure EXPLORER_TEST_NODE')
        script = HARNESS + '\n(async()=>{\nconst mode=' + repr(mode) + ';\n' + scenario + '\n})().catch(e=>{console.error(e);process.exitCode=1;});'
        for package in ('music_analyzer', 'music_explorer'):
            with self.subTest(package=package):
                app = ROOT / package / 'frameworks/explorer/assets/app.js'
                result = subprocess.run([NODE, '-e', script, str(app)], cwd=ROOT,
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_search_and_selected_detail_work_through_pending_automatic_graph(self):
        self.run_browser(PENDING_SCENARIO)

    def test_search_detail_and_scoped_graph_retry_work_after_automatic_graph_failure(self):
        self.run_browser(FAILURE_RETRY_SCENARIO)

    def test_automatic_graph_renders_despite_failed_search_and_preserves_search_retry(self):
        self.run_browser(SEARCH_FAILURE_SCENARIO)

    def test_inline_loading_and_retry_replace_manual_load_graph_button_and_copy(self):
        self.run_browser(r"""
boot(); await flush();
assert(!graphButtons().some(n=>/^load graph$/i.test(n.innerText)),
  'automatic startup removes obsolete manual Load graph button');
assert(!/use the load graph button|graph not loaded/i.test(graphStatus()),
  'automatic startup removes obsolete manual graph instruction');
assert.equal(graphRequests().length,1);
assert(/loading graph/i.test(graphStatus()),'automatic graph request exposes inline loading');
assert(walk(roots['graph-load-status']).some(n=>n.getAttribute('role')==='status'&&/loading/i.test(n.innerText)),
  'inline loading feedback is announced');
assertInlineOnly();
graphGate.resolve(response('graph temporarily unavailable',false)); await flush();
assert(/graph temporarily unavailable/i.test(graphStatus()));
assert(graphRetry(),'failed automatic graph exposes retry instead of Load graph');
assert(!graphButtons().some(n=>/^load graph$/i.test(n.innerText)));
assertInlineOnly();
""")

    def test_state_startup_failure_does_not_block_search_detail_or_successful_graph(self):
        """A distinct RED: existing startup state error leaves a blocking overlay."""
        self.run_browser(r"""
stateGate=deferred(); stateGate.resolve(response('state temporarily unavailable',false));
await start('baseline-control');
assert(/state temporarily unavailable/i.test(roots['loading-error'].innerText),
  'fixture establishes state startup failure rather than a graph failure');
await searchFor('Matching');
assert.equal(rows().length,1);
await selectResult();
graphGate.resolve(response(graphBody)); await flush();
assert(/graph ready/i.test(graphStatus()),'state failure must not prevent graph rendering');
assert(canvasPaints.length>0);
assertInlineOnly();
""")

    def test_baseline_control_existing_graph_fixture_and_pending_search_detail_are_valid(self):
        self.run_browser(PENDING_SCENARIO, mode='baseline-control')

    def test_baseline_control_existing_graph_failure_and_scoped_retry_are_valid(self):
        self.run_browser(FAILURE_RETRY_SCENARIO, mode='baseline-control')

    def test_baseline_control_existing_graph_succeeds_through_failed_search(self):
        self.run_browser(SEARCH_FAILURE_SCENARIO, mode='baseline-control')


if __name__ == '__main__':
    unittest.main()
