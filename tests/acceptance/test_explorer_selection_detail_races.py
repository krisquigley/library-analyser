"""Deferred selection/history contracts for #70, for both packaged JS assets.

These intentionally red feedback tests do not implement the proposed UI. Passing
controls separately protect the existing POST gate and stale-response guards.
Node/fixture failures are errors, never accepted as evidence of missing feedback.
"""
from pathlib import Path
import os
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
ASSETS = tuple(ROOT / package / "frameworks/explorer/assets/app.js"
               for package in ("music_explorer", "music_analyzer"))
NODE = os.environ.get("EXPLORER_TEST_NODE") or shutil.which("node") or "/tmp/node-host-v24"

HARNESS = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const requests = [];
const frames = [];
function element(tag) {
  return {tagName:tag.toUpperCase(), children:[], dataset:{}, style:{}, attributes:{}, hidden:false,
    ownText:'', get textContent(){return this.ownText + this.children.map(c=>c.textContent||'').join(' ');},
    set textContent(v){this.ownText=String(v); this.children=[];},
    append(...nodes){this.children.push(...nodes);},
    replaceChildren(...nodes){this.ownText=''; this.children=nodes;},
    setAttribute(k,v){this.attributes[k]=String(v);}, getAttribute(k){return this.attributes[k]??null;},
    removeAttribute(k){delete this.attributes[k];}, querySelector(){return null;}};
}
const roots = {detail:element('section')};
roots.detail.id='detail';
const storage = new Map();
const context = vm.createContext({console, URLSearchParams, setTimeout, clearTimeout,
  requestAnimationFrame:callback=>frames.push(callback),
  sessionStorage:{getItem:k=>storage.get(k)??null,setItem:(k,v)=>storage.set(k,v)},
  fetch(path, options={}) {
    let resolve, reject;
    const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});
    const request={path,method:options.method||'GET',body:options.body?JSON.parse(options.body):null,
      ok(value){resolve({ok:true,json:async()=>value});},
      fail(message){resolve({ok:false,text:async()=>message});}, reject};
    requests.push(request); return promise;
  }});
// Load real functions unchanged; attach DOM afterwards to isolate selection from startup.
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
context.document={createElement:element,createTextNode:value=>({textContent:String(value)}),
  getElementById:id=>roots[id]||find(roots.detail,n=>n.id===id),
  querySelectorAll:()=>[],querySelector:()=>null};
function find(node, predicate){if(predicate(node))return node;for(const c of node.children||[]){const hit=find(c,predicate);if(hit)return hit;}return null;}
const snapshot=(id, epoch=7, history=[])=>({current_track_id:id,selection_epoch:epoch,history});
const detail=id=>({handle:id,metadata:{common:[['title','DETAIL '+id]],tags:[]},fields:{}});
context.setStateForTesting(snapshot(null)); context.syncSelectionEpoch(snapshot(null));
const flush=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
const nextRefreshFrame=async()=>{await flush();assert(frames.length,'fixture expected refresh frame');frames.shift()(0);await flush();};
const settled=promise=>promise.then(()=>({ok:true}),error=>({ok:false,message:error.message}));
const select=id=>settled(context.setCurrent(id));
const req=(path,index=0)=>{const matches=requests.filter(r=>r.path===path);assert(matches[index], 'fixture expected request '+path+' #'+index);return matches[index];};
const ids=()=>requests.filter(r=>/^\/api\/tracks\//.test(r.path)).map(r=>r.path);
function visibleNodes(node=roots.detail){if(node.hidden||node.getAttribute?.('aria-hidden')==='true'||node.style?.display==='none'||node.style?.visibility==='hidden')return [];return [node,...(node.children||[]).flatMap(c=>visibleNodes(c))];}
const text=()=>visibleNodes().map(n=>n.ownText||'').join(' ');
const statusText=()=>visibleNodes().filter(n=>['status','alert'].includes(n.getAttribute?.('role'))).map(n=>visibleNodes(n).map(c=>c.ownText||'').join(' ')).join(' ');
const loading=()=> /loading|fetching|preparing/i.test(statusText());
const errorVisible=()=> /error|failed|unavailable|unable|could not/i.test(statusText());
async function accept(id, index=0, epoch=7, history=[], accepted=true) {req('/api/current',index).ok({...snapshot(id,epoch,history),selection_accepted:accepted});await flush();}
async function finish(id,index=0){req('/api/tracks/'+id,index).ok(detail(id));await flush();}
async function paintInitial(){const first=select('OLD');await accept('OLD');await finish('OLD');assert((await first).ok);assert(text().includes('DETAIL OLD'),'fixture renders actual detail metadata');}
async function history(path, id, epoch, items=[]){const operation=settled(context.applyHistorySelection(path));req(path).ok(snapshot(id,epoch,items));await nextRefreshFrame();req('/api/state').ok(snapshot(id,epoch,items));await flush();if(id)await finish(id);assert((await operation).ok);}
"""

SCENARIOS = {
    "post_gate_and_exact_detail_count": r"""
const a=select('A'); assert.equal(ids().length,0,'detail cannot precede accepted POST');
await accept('A'); assert.deepEqual(ids(),['/api/tracks/A']); await finish('A'); assert((await a).ok);
assert(text().includes('DETAIL A')); assert.equal(requests.length,2,'selection does not refresh list/state/graph');
""",
    "stale_post_does_not_fetch_or_replace_latest": r"""
const a=select('A'); const b=select('B'); await accept('B',1); await finish('B'); assert((await b).ok);
await accept('A',0); assert((await a).ok); assert.deepEqual(ids(),['/api/tracks/B']);
assert.equal(context.getStateForTesting().current_track_id,'B'); assert(text().includes('DETAIL B'));
""",
    "stale_post_failure_does_not_poison_latest": r"""
const a=select('A');const b=select('B');await accept('B',1);await finish('B');assert((await b).ok);
req('/api/current',0).fail('A selection transport failed');await a;await flush();
assert.deepEqual(ids(),['/api/tracks/B']);assert.equal(context.getStateForTesting().current_track_id,'B');
assert(text().includes('DETAIL B'));assert(!errorVisible());assert(!loading());
""",
    "stale_detail_success_does_not_replace_latest": r"""
const a=select('A');await accept('A');const b=select('B');await accept('B',1);await finish('B');assert((await b).ok);
await finish('A');assert((await a).ok);assert(text().includes('DETAIL B'));assert(!text().includes('DETAIL A'));
assert.deepEqual(ids(),['/api/tracks/A','/api/tracks/B']);
""",
    "stale_detail_failure_does_not_poison_latest": r"""
const a=select('A');await accept('A');const b=select('B');await accept('B',1);await finish('B');assert((await b).ok);
req('/api/tracks/A').fail('A transport failed');await a;await flush();
assert(text().includes('DETAIL B'));assert(!errorVisible(),'stale error must not replace current detail');assert(!loading());
""",
    "authoritative_rejection_fetches_server_current_not_rejected_intent": r"""
const a=select('REJECTED');await accept('SERVER',0,8,['EARLIER'],false);
assert.deepEqual(ids(),['/api/tracks/SERVER']);await finish('SERVER');assert((await a).ok);
assert.equal(context.getStateForTesting().current_track_id,'SERVER');
assert.deepEqual(Array.from(context.getStateForTesting().history),['EARLIER']);assert(text().includes('DETAIL SERVER'));
""",
    "reset_invalidates_pending_post_and_preserves_epoch_token": r"""
const a=select('A'); const original=req('/api/current').body;
// A POST evaluated after reset returns the authoritative new epoch, even if its UI intent is stale.
await history('/api/reset',null,8,[]);await accept(null,0,8,[],false);await a;
assert.equal(context.getStateForTesting().current_track_id,null);assert.equal(text(),'');assert.deepEqual(ids(),[]);
const b=select('B');const next=req('/api/current',1).body;
assert.equal(next.selection_epoch,8);assert.equal(next.selection_token,original.selection_token+1);
assert.equal(next.selection_client_id,original.selection_client_id);
await accept('B',1,8);await finish('B');assert((await b).ok);
""",
    "undo_invalidates_pending_detail_and_preserves_history": r"""
const a=select('A');await accept('A');await history('/api/undo','PRIOR',8,['ROOT']);
await finish('A');await a;assert.equal(context.getStateForTesting().current_track_id,'PRIOR');
assert.deepEqual(Array.from(context.getStateForTesting().history),['ROOT']);
assert(text().includes('DETAIL PRIOR'));assert(!text().includes('DETAIL A'));
const b=select('B');assert.equal(req('/api/current',1).body.selection_epoch,8);
await accept('B',1,8,['ROOT','PRIOR']);await finish('B');await b;
""",
    "refresh_while_post_pending_does_not_fetch_unaccepted_intent": r"""
const a=select('A');const refresh=settled(context.refresh());
await nextRefreshFrame();req('/api/state').ok(snapshot(null,7,[]));await flush();
assert.deepEqual(ids(),[],'#70: refresh must not GET optimistic A before POST acceptance');
await accept('A');assert.deepEqual(ids(),['/api/tracks/A'],'#70: accepted current intent needs exactly one detail GET');
await finish('A');assert((await a).ok);assert((await refresh).ok);assert(text().includes('DETAIL A'));
""",
    "current_post_failure_shows_scoped_error_without_unaccepted_detail": r"""
await paintInitial();const a=select('A');req('/api/current',1).fail('Current selection failed');await a;await flush();
assert.deepEqual(ids(),['/api/tracks/OLD'],'#70: failed POST cannot authorize A detail');
assert(errorVisible(),'#70: current POST failure needs visible scoped failure feedback');assert(!loading());
assert(!text().includes('DETAIL OLD'),'#70: failed current intent cannot leave ghost old panel');
""",
    "latest_intent_loading_is_immediate_before_post": r"""
await paintInitial(); const a=select('A');
assert(loading(),'#70: latest selection needs scoped loading before POST resolves');
assert(!text().includes('DETAIL OLD'),'#70: old panel must not masquerade as new selection');
""",
    "latest_intent_owns_feedback_through_post_then_detail": r"""
const a=select('A');await accept('A');const b=select('B');await finish('A');await a;
assert(loading(),'#70: stale detail completion must leave latest B loading while its POST waits');
await accept('B',1);assert(loading(),'#70: B loading must continue through accepted POST to detail');
await finish('B');assert((await b).ok);assert(!loading());assert(text().includes('DETAIL B'));
""",
    "authoritative_rejection_reconciles_pending_detail_feedback": r"""
await paintInitial();const a=select('REJECTED');await accept('SERVER',1,8,['EARLIER'],false);
assert(loading(),'#70: authoritative current needs loading while its detail waits');
assert(!text().includes('DETAIL OLD'),'#70: rejected click must not leave ghost old panel');
await finish('SERVER');assert((await a).ok);assert(!loading());assert(text().includes('DETAIL SERVER'));
""",
    "undo_replaces_pending_detail_with_history_loading": r"""
await paintInitial();const a=select('A');await accept('A',1);
const undo=settled(context.applyHistorySelection('/api/undo'));
req('/api/undo').ok(snapshot('PRIOR',8,['ROOT']));await nextRefreshFrame();
req('/api/state').ok(snapshot('PRIOR',8,['ROOT']));await flush();await finish('A');await a;
assert(loading(),'#70: stale detail must not clear undo current-detail loading');
assert(!text().includes('DETAIL OLD'),'#70: undo must not show ghost old detail while waiting');
await finish('PRIOR');assert((await undo).ok);assert(!loading());assert(text().includes('DETAIL PRIOR'));
""",
}


class SelectionDetailRaceTests(unittest.TestCase):
    def run_scenario(self, name):
        if not Path(NODE).is_file():
            self.fail(f"Node prerequisite unavailable: {NODE}")
        for asset in ASSETS:
            with self.subTest(asset=str(asset.relative_to(ROOT)), scenario=name):
                script = HARNESS + "\n(async()=>{\n" + SCENARIOS[name] + "\n})().catch(e=>{console.error(e);process.exitCode=1;});"
                result = subprocess.run([NODE, "-e", script, str(asset)], capture_output=True,
                                        text=True, timeout=15, cwd=ROOT)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


def _scenario_test(name):
    def test(self):
        self.run_scenario(name)
    return test


for _name in SCENARIOS:
    setattr(SelectionDetailRaceTests, "test_" + _name, _scenario_test(_name))

if __name__ == "__main__":
    unittest.main()
