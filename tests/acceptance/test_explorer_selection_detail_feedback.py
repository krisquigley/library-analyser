"""Refs #70: red-only selected-detail feedback contracts for both web assets.

Run the unmodified complete delivery scripts with fake DOM and deferred HTTP.
Controls separately prove accepted detail and graph adapters already work; these
are semantic lifecycle checks, not browser paint or performance measurements.
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
const fs = require('node:fs'), vm = require('node:vm');
const paints=[];
const canvasContext={clearRect(){},fillRect(){},beginPath(){},arc(...args){paints.push(args);},fill(){}};
function element(tag){return {
  tagName:tag.toUpperCase(),id:'',children:[],attributes:{},dataset:{},style:{},
  className:'',value:'',textContent:'',hidden:false,disabled:false,
  append(...nodes){this.children.push(...nodes);},
  replaceChildren(...nodes){this.children=[...nodes];this.textContent='';},
  replaceChild(node,old){const i=this.children.indexOf(old);assert(i>=0);this.children.splice(i,1,node);return old;},
  setAttribute(k,v){this.attributes[k]=String(v);},getAttribute(k){return this.attributes[k]??null;},
  removeAttribute(k){delete this.attributes[k];},getContext(){return canvasContext;},
  querySelector(selector){return walk(this).find(n=>n!==this&&n.tagName===selector.toUpperCase())||null;},
  get innerText(){return [this.textContent,...this.children.filter(n=>!n.hidden).map(n=>visibleText(n))].join(' ');}
};}
function walk(root){return [root,...root.children.flatMap(walk)];}
function visibleNodes(root){
  const hidden=root.hidden||root.getAttribute('aria-hidden')==='true'||root.style.display==='none'||['hidden','collapse'].includes(root.style.visibility);
  return hidden?[]:[root,...root.children.flatMap(visibleNodes)];
}
function visibleText(root){return visibleNodes(root).map(n=>n.textContent).join(' ');}
function deferred(){let resolve,reject;const promise=new Promise((r,j)=>{resolve=r;reject=j;});return {promise,resolve,reject};}
function response(body,ok=true){return {ok,json:async()=>body,text:async()=>String(body)};}
function detail(id,title){return {handle:id,fields:{},metadata:{common:[['title',title]],tags:[]}};}
const roots={};
for(const id of ['tracks','track-search','undo','reset','controls','detail','graph-load-status',
                'loading-surface','loading-status','loading-error','loading-retry']){
  roots[id]=element(id==='track-search'?'input':['undo','reset'].includes(id)?'button':'div');roots[id].id=id;
}
roots['loading-surface'].className='loading-surface';
roots['loading-surface'].setAttribute('aria-busy','true');
const requests=[],graphGate=deferred();
let stateBody={current_track_id:null,selection_epoch:0};
let postResponder=options=>{
  stateBody={...stateBody,current_track_id:JSON.parse(options.body).track_id};
  return response(stateBody);
};
let detailResponder=id=>response(detail(id,id==='old'?'Previously selected title':'Accepted new title'));
let graphResponder=()=>graphGate.promise;
const context=vm.createContext({console,URLSearchParams,URL,
  document:{createElement:element,createTextNode:t=>({...element('text'),textContent:String(t)}),
    getElementById(id){return roots[id]||Object.values(roots).flatMap(walk).find(n=>n.id===id)||null;},
    querySelectorAll(){return walk(roots.tracks).filter(n=>n.tagName==='TR'&&n.dataset.trackId);}},
  requestAnimationFrame:fn=>{fn(0);return 1;},setTimeout,clearTimeout,
  fetch:async(path,options={})=>{
    const url=new URL(String(path),'http://example.test');requests.push({url,options});
    if(url.pathname==='/api/state')return response(stateBody);
    if(url.pathname==='/api/current')return postResponder(options);
    if(url.pathname==='/api/mood-axis-graph')return graphResponder();
    if(url.pathname==='/api/tracks/summary')return response({tracks:[{handle:'new',title:'New result',artist:'Artist'}],next_cursor:null,metadata:{track_count:1}});
    if(url.pathname.startsWith('/api/tracks/'))return detailResponder(decodeURIComponent(url.pathname.split('/').at(-1)));
    throw new Error('Unexpected request '+path);
  }
});
async function flush(){for(let i=0;i<40;i++)await Promise.resolve();}
function paths(start=0){return requests.slice(start).map(r=>r.url.pathname);}
function getCount(id){return requests.filter(r=>r.url.pathname==='/api/tracks/'+id).length;}
function statusNodes(){return visibleNodes(roots.detail).filter(n=>['status','alert'].includes(n.getAttribute('role')));}
function retry(){return visibleNodes(roots.detail).find(n=>n.tagName==='BUTTON'&&!n.disabled&&/retry/i.test(visibleText(n)));}
function assertNotBlocking(){
  const overlay=roots['loading-surface'];
  assert(overlay.hidden||!/(^|\s)(active|error)(\s|$)/.test(overlay.className),'selected detail must not activate a blocking library overlay');
  assert.equal(roots['track-search'].disabled,false,'search stays enabled while detail is pending or failed');
}
function assertLoading(){
  assert(statusNodes().some(n=>/load/i.test(visibleText(n))),'selection intent must immediately expose a visible loading status inside #detail');
  assert(!roots.detail.innerText.includes('Previously selected title'),'old track evidence must not masquerade as the newly selected detail');
  assert(!retry(),'pending detail must not offer duplicate retry');assertNotBlocking();
}
function assertFailure(){
  assert(statusNodes().some(n=>/unavailable/i.test(visibleText(n))||/fail|error|unable|could not/i.test(visibleText(n))),
    'failed current detail must expose an explicit visible error inside #detail');
  assert(!statusNodes().some(n=>/loading/i.test(visibleText(n))),'failure must leave loading state');
  assert(!roots.detail.innerText.includes('Previously selected title'),'failure must not retain ghost old detail');
  assert(retry(),'failed current detail must offer a visible scoped retry button');assertNotBlocking();
}
function capture(promise){return promise.then(()=>null,error=>error);}
async function boot(){
  vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context,{filename:process.argv[1]});await flush();
  // Use baseline's real explicit graph path if automatic startup is absent.
  // Graph auto-start is not the subject of this detail-feedback slice.
  if(!paths().includes('/api/mood-axis-graph')){capture(context.loadGraph());await flush();}
  assert.equal(paths().filter(p=>p==='/api/mood-axis-graph').length,1,'fixture starts one real pending graph request');
  await context.setCurrent('old');await flush();
  assert(roots.detail.innerText.includes('Previously selected title'),'positive fixture precondition: real renderDetail displays prior metadata');
  assertNotBlocking();
}
const graphBody={dto_version:'mood-axis-graph-indexed-v1',selected_mood:'calm',available_moods:['calm'],
  axis:[{key:'x',label:'Valence',scale:'native'},{key:'y',label:'Arousal',scale:'native'},{key:'z',label:'Mood',scale:'native'}],
  nodes:[['new','New result',0.2,0.2,0.3,0.3,0.4,0.4,120,0.4,[],[]]],links:[],unpositioned:[],
  genre_labels:[],reason_text:[],explanation_table:[],provenance_table:[],metadata:{graph_status:{state:'ready'}}};
"""


class SelectionDetailFeedbackTests(unittest.TestCase):
    def run_browser(self, scenario):
        self.assertTrue(NODE, 'Node required: configure EXPLORER_TEST_NODE; no skip acceptance')
        script = HARNESS + '\n(async()=>{\n' + scenario + '\n})().catch(e=>{console.error(e);process.exitCode=1;});'
        for package in ('music_analyzer', 'music_explorer'):
            with self.subTest(package=package):
                app = ROOT / package / 'frameworks/explorer/assets/app.js'
                result = subprocess.run([NODE, '-e', script, str(app)], cwd=ROOT,
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_selection_intent_immediately_replaces_old_detail_before_post_acceptance(self):
        self.run_browser(r"""
await boot();const postGate=deferred();postResponder=()=>postGate.promise;
const before=requests.length;const selected=capture(context.setCurrent('new'));
assert.deepEqual(paths(before),['/api/current'],'detail GET must remain behind accepted POST');
assert.equal(getCount('new'),0);assertLoading();
postGate.resolve(response({current_track_id:'new',selection_epoch:0}));await selected;
assert(roots.detail.innerText.includes('Accepted new title'));
assert.deepEqual(paths(before),['/api/current','/api/tracks/new']);
""")

    def test_accepted_selection_has_scoped_loading_until_its_detail_arrives(self):
        self.run_browser(r"""
await boot();const gate=deferred();detailResponder=()=>gate.promise;
const before=requests.length;const selected=capture(context.setCurrent('new'));await flush();
assert.deepEqual(paths(before),['/api/current','/api/tracks/new']);assertLoading();
gate.resolve(response(detail('new','Accepted new title')));await selected;await flush();
assert(roots.detail.innerText.includes('Accepted new title'));
assert.equal(statusNodes().filter(n=>/loading/i.test(visibleText(n))).length,0);
assert(!retry(),'success must remove retry');assert.equal(getCount('new'),1);
""")

    def test_http_detail_failure_is_visible_and_retry_only_fetches_current_detail(self):
        self.run_failure_retry('http')

    def test_transport_detail_failure_is_visible_and_retry_only_fetches_current_detail(self):
        self.run_failure_retry('transport')

    def run_failure_retry(self, failure):
        self.run_browser("const failure=" + repr(failure) + ";\n" + r"""
await boot();const gate=deferred();detailResponder=()=>gate.promise;
const selected=capture(context.setCurrent('new'));await flush();
assert.equal(getCount('new'),1,'fixture must reach selected GET before failing it');
if(failure==='http')gate.resolve(response('detail temporarily unavailable',false));
else gate.reject(new Error('detail temporarily unavailable'));
await selected;await flush();assertFailure();
const retryGate=deferred();detailResponder=()=>retryGate.promise;
const before=requests.length;capture(Promise.resolve(retry().onclick()));await flush();
assert.deepEqual(paths(before),['/api/tracks/new'],'detail retry must not POST intent or refresh state, summaries, or graph');
assertLoading();assert.equal(getCount('new'),2);
retryGate.resolve(response(detail('new','Recovered current title')));await flush();
assert(roots.detail.innerText.includes('Recovered current title'),'retry paints accepted current metadata');
assert(!retry(),'successful retry removes retry control');
assert.equal(statusNodes().length,0,'success removes pending/error feedback');
assert.deepEqual(paths(before),['/api/tracks/new']);
""")

    def test_late_retry_success_cannot_replace_newer_selected_detail(self):
        self.run_late_retry('success')

    def test_late_retry_failure_cannot_attach_error_or_retry_to_newer_detail(self):
        self.run_late_retry('failure')

    def run_late_retry(self, outcome):
        self.run_browser("const outcome=" + repr(outcome) + ";\n" + r"""
await boot();detailResponder=()=>response('detail temporarily unavailable',false);
await capture(context.setCurrent('new'));await flush();
assert.equal(getCount('new'),1,'initial current detail GET reaches failure');
// This is intentionally the RED gate on base: no invented error/retry fixture.
assertFailure();
const retryGate=deferred();detailResponder=id=>id==='new'?retryGate.promise:response(detail(id,'Newer accepted title'));
const retryStart=requests.length;
const retryCompletion=capture(Promise.resolve(retry().onclick()));await flush();
assert.deepEqual(paths(retryStart),['/api/tracks/new'],'retry posts no intent and refreshes no state, summaries, or graph');
assert.equal(getCount('new'),2,'one retry GET for failed selected track');assertLoading();
const selectionStart=requests.length;
assert.equal(await capture(context.setCurrent('other')),null);await flush();
assert.deepEqual(paths(selectionStart),['/api/current','/api/tracks/other']);
assert(roots.detail.innerText.includes('Newer accepted title'),'newer accepted selection paints its own metadata before retry settles');
assert.equal(statusNodes().length,0);assert(!retry());
const newerDetail=roots.detail.innerText,beforeLate=requests.length;
if(outcome==='success')retryGate.resolve(response(detail('new','Stale retried title')));
else retryGate.resolve(response('stale retry temporarily unavailable',false));
await retryCompletion;await flush();
assert.equal(roots.detail.innerText,newerDetail,'late retry completion must not replace newer selected detail');
assert(!roots.detail.innerText.includes('Stale retried title'));
assert(!roots.detail.innerText.includes('stale retry temporarily unavailable'));
assert.equal(statusNodes().length,0,'late retry must not attach loading/error to newer current detail');
assert(!retry(),'late retry must not attach retry action to newer successful current detail');
assert.equal(requests.length,beforeLate,'late retry completion must not start another request');
assert.equal(getCount('other'),1);assert.equal(getCount('new'),2);assertNotBlocking();
""")

    def test_graph_completion_cannot_remove_pending_detail_loading(self):
        self.run_browser(r"""
await boot();const gate=deferred();detailResponder=()=>gate.promise;
const selected=capture(context.setCurrent('new'));await flush();
assert.equal(getCount('new'),1);const before=requests.length;
graphGate.resolve(response(graphBody));await flush();
assert(/graph ready/i.test(roots['graph-load-status'].innerText),'graph completes independently of pending detail');
assert(paints.length>0,'graph completion exercises actual canvas adapter');
assert.equal(requests.length,before,'graph completion must not restart selected detail');
assertLoading();gate.resolve(response(detail('new','Accepted new title')));await selected;
""")

    def test_failed_detail_does_not_stop_independent_graph_success(self):
        self.run_browser(r"""
await boot();detailResponder=()=>response('detail temporarily unavailable',false);
await capture(context.setCurrent('new'));await flush();const before=requests.length;
graphGate.resolve(response(graphBody));await flush();
assert(/graph ready/i.test(roots['graph-load-status'].innerText));assert(paints.length>0);
assert.equal(requests.length,before,'graph success must not refetch failed detail');assertFailure();
""")

    def test_control_accepted_detail_is_post_gated_and_works_with_pending_graph(self):
        self.run_browser(r"""
await boot();const postGate=deferred(),detailGate=deferred();
postResponder=()=>postGate.promise;detailResponder=()=>detailGate.promise;
const before=requests.length;const selected=capture(context.setCurrent('new'));await flush();
assert.deepEqual(paths(before),['/api/current']);assert.equal(getCount('new'),0);
postGate.resolve(response({current_track_id:'new',selection_epoch:0}));await flush();
assert.deepEqual(paths(before),['/api/current','/api/tracks/new']);
detailGate.resolve(response(detail('new','Accepted new title')));assert.equal(await selected,null);
assert(roots.detail.innerText.includes('Accepted new title'));
assert(/loading graph/i.test(roots['graph-load-status'].innerText),'graph remains unresolved while detail succeeds');
assert.equal(getCount('new'),1);assertNotBlocking();
""")

    def test_control_graph_failure_does_not_prevent_accepted_detail(self):
        self.run_browser(r"""
await boot();graphGate.resolve(response('graph temporarily unavailable',false));await flush();
assert(/graph temporarily unavailable/i.test(roots['graph-load-status'].innerText));
const before=requests.length;await context.setCurrent('new');await flush();
assert(roots.detail.innerText.includes('Accepted new title'));
assert.deepEqual(paths(before),['/api/current','/api/tracks/new']);assertNotBlocking();
""")

    def test_control_graph_completes_during_pending_detail_without_refetching_it(self):
        self.run_browser(r"""
await boot();const gate=deferred();detailResponder=()=>gate.promise;
const selected=capture(context.setCurrent('new'));await flush();assert.equal(getCount('new'),1);
const before=requests.length;graphGate.resolve(response(graphBody));await flush();
assert(/graph ready/i.test(roots['graph-load-status'].innerText));assert(paints.length>0);
assert.equal(requests.length,before);
gate.resolve(response(detail('new','Accepted new title')));assert.equal(await selected,null);
assert(roots.detail.innerText.includes('Accepted new title'));assert.equal(getCount('new'),1);
""")


if __name__ == '__main__':
    unittest.main()
