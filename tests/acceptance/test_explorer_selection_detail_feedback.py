"""Refs #70: red-only selected-detail feedback contracts for both web assets.

Run the unmodified complete delivery scripts with fake DOM and deferred HTTP, driven as the
listener does: tracks are chosen by searching and clicking their row (#146), never by calling the page.
Controls separately prove accepted detail and graph adapters already work; these
are semantic lifecycle checks, not browser paint or performance measurements.
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
    if(url.pathname==='/api/tracks/summary'){const id=url.searchParams.get('query');
      return response({tracks:[{handle:id,title:id==='new'?'New result':'Result '+id,artist:'Artist'}],next_cursor:null,metadata:{track_count:1}});}
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
// The listener's way to a track: type its name, wait out the typing pause, then click its row.
async function showRow(id){const search=roots['track-search'];search.value=id;search.oninput();
  await new Promise(resolve=>setTimeout(resolve,200));await flush();}
function pick(id){const row=walk(roots.tracks).find(n=>n.tagName==='TR'&&n.dataset.trackId===id);
  assert(row,'a search row for '+id);return capture(Promise.resolve(row.children[0].children[0].onclick()));}
async function choose(id){await showRow(id);return pick(id);}
async function boot(){
  vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context,{filename:process.argv[1]});await flush();
  assert.equal(paths().filter(p=>p==='/api/mood-axis-graph').length,1,'startup starts one real pending graph request');
  await choose('old');await flush();
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
                app = explorer_app_script(ROOT / package / 'frameworks/explorer/assets/app.js')
                result = subprocess.run([NODE, '-e', script, str(app)], cwd=ROOT,
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_graph_completion_cannot_remove_pending_detail_loading(self):
        self.run_browser(r"""
await boot();const gate=deferred();detailResponder=()=>gate.promise;
await showRow('new');const selected=pick('new');await flush();
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
await choose('new');await flush();const before=requests.length;
graphGate.resolve(response(graphBody));await flush();
assert(/graph ready/i.test(roots['graph-load-status'].innerText));assert(paints.length>0);
assert.equal(requests.length,before,'graph success must not refetch failed detail');assertFailure();
""")

if __name__ == '__main__':
    unittest.main()
