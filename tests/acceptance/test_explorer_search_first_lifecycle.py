"""PR1 search-first lifecycle contracts, executed against each packaged browser asset.

The VM evaluates the complete delivery script, including its real startup wiring.
Only browser boundaries (DOM, fetch, clock/frame scheduling) are faked. No
production functions or state transitions are replaced. Node absence is an error,
not a silently skipped acceptance gate. Baseline controls are named explicitly.
"""
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from tests.support.explorer_app_bundle import explorer_app_script


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
const fixtureTrack={handle:'result',title:'Matching title',artist:'Artist'};
const roots={};
for(const id of ['tracks','track-search','undo','reset','controls','detail','graph-load-status',
                  'library-loading','loading-status','loading-error','loading-retry']) {
  roots[id]=element(id==='track-search'?'input':id==='undo'||id==='reset'?'button':'div');
  roots[id].id=id;
}
const search=roots['track-search'], tracks=roots.tracks;
let timerId=0, now=0;
const timers=new Map(), requests=[];
let stateBody={current_track_id:null,selection_epoch:0};
let stateGate=null;
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
    if(url.pathname==='/api/state') return stateGate?stateGate.promise:response(stateBody);
    if(url.pathname==='/api/tracks/summary') return summaryResponder(url);
    if(url.pathname==='/api/undo'||url.pathname==='/api/reset') return response(stateBody);
    if(url.pathname==='/api/current') {
      stateBody={...stateBody,current_track_id:JSON.parse(options.body).track_id};
      return response(stateBody);
    }
    if(url.pathname.startsWith('/api/tracks/')) return response({handle:url.pathname.split('/').at(-1),stages:[],metadata:{}});
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
"""


class ExplorerSearchFirstLifecycleTests(unittest.TestCase):
    def run_browser(self, scenario):
        self.assertTrue(NODE, 'Node is required for search-first acceptance; configure EXPLORER_TEST_NODE')
        script = HARNESS + '\n(async()=>{\n' + scenario + '\n})().catch(e=>{console.error(e);process.exitCode=1;});'
        for package in ('music_analyzer', 'music_explorer'):
            with self.subTest(package=package):
                app = explorer_app_script(ROOT / package / 'frameworks/explorer/assets/app.js')
                result = subprocess.run([NODE, '-e', script, str(app)], cwd=ROOT,
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_startup_has_no_summary_or_list_request_and_no_rows(self):
        self.run_browser(r"""
boot(); await flush();
assert.equal(requests.filter(r=>['/api/tracks','/api/tracks/summary','/api/track-summaries'].includes(r.url.pathname)).length,0,
  'startup must not fetch any sidebar list solely to fill results');
assert.equal(rows().length,0,'results remain empty until a nonblank search');
assert(requests.some(r=>r.url.pathname==='/api/state'),'normal state startup is retained');
""")

    def test_search_is_wired_while_initial_state_request_is_pending(self):
        self.run_browser(r"""
stateGate=deferred(); boot(); await flush();
assert(requests.some(r=>r.url.pathname==='/api/state'));
input('Matching'); await advance(150);
assert.equal(summaryRequests().length,1,'search is independent of pending initial state');
assert.equal(summaryRequests()[0].url.searchParams.get('query'),'Matching');
assert.equal(summaryRequests()[0].url.searchParams.get('limit'),'100');
assert.equal(rows().length,1);
stateGate.resolve(response(stateBody)); await flush();
assert.equal(summaryRequests().length,1,'finishing state must not overwrite searched results');
""")

    def test_refresh_preserves_search_and_selected_detail_without_list_fetch(self):
        self.run_browser(r"""
stateBody={current_track_id:'selected',selection_epoch:0};
boot(); await flush(); await searchFor('Matching');
const before=requests.length;
await context.refresh(); await flush();
const refreshed=requests.slice(before);
assert.equal(refreshed.filter(r=>r.url.pathname==='/api/tracks/summary').length,0,'refresh must not replace the search with catalogue page one');
assert.equal(search.value,'Matching'); assert.deepEqual(rows().map(r=>r.dataset.trackId),['result']);
assert.equal(refreshed.filter(r=>r.url.pathname==='/api/tracks/selected').length,1,'selected detail still refreshes normally');
""")

    def test_history_and_reset_preserve_search_results_without_list_fetch(self):
        for action in ('undo', 'reset'):
            with self.subTest(action=action):
                self.run_browser("const id=" + repr(action) + r""";
boot(); await flush(); await searchFor('Matching');
const before=requests.length;
await roots[id].onclick(); await flush();
const history=requests.slice(before);
assert(history.some(r=>r.url.pathname==='/api/'+id&&r.options.method==='POST'));
assert.equal(history.filter(r=>r.url.pathname==='/api/tracks/summary').length,0,id+' must not refill the sidebar');
assert.equal(search.value,'Matching'); assert.deepEqual(rows().map(r=>r.dataset.trackId),['result']);
""")

if __name__ == '__main__':
    unittest.main()
