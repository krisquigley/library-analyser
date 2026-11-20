"""The selection and detail tests' shared Node harness for the Explorer app (#146).

The page starts as in a browser, at ``?diagnostics``; each request waits until the scenario answers it. A
scenario chooses a listed track by clicking its row (``select``) and uses Undo or Reset by their buttons
(``press``, ``history``), and observes the page through its seam, the fake DOM and its requests.
"""
from pathlib import Path
import os
import shutil
from tests.support.explorer_app_bundle import explorer_app_script
from tests.support.explorer_page_harness import FAKE_DOM


ROOT = Path(__file__).resolve().parents[2]


ASSETS = tuple(explorer_app_script(ROOT / package / "frameworks/explorer/assets/app/main/main.js")
               for package in ("music_explorer", "music_analyzer"))


NODE = os.environ.get("EXPLORER_TEST_NODE") or shutil.which("node") or "/tmp/node-host-v24"


HARNESS = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const requests = [];
const frames = [];
""" + FAKE_DOM + r"""
const storage = new Map();
const pendingTimers = [];
// The tracks a scenario chooses; startup lists them by a real search.
const LISTED = ['OLD', 'A', 'PRIOR'];
const context = vm.createContext({console, URL, URLSearchParams, document,
  location:{search:'?diagnostics',href:'http://127.0.0.1/?diagnostics'},
  setTimeout:callback=>{pendingTimers.push(callback);return pendingTimers.length;}, clearTimeout(){},
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
// The page starts as in a browser, at ?diagnostics.
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
const seam = context.explorerDiagnostics;
const snapshot=(id, epoch=7, history=[])=>({current_track_id:id,selection_epoch:epoch,history});
const detail=id=>({handle:id,metadata:{common:[['title','DETAIL '+id]],tags:[]},fields:{}});
const flush=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
async function startupWork(){for(let round=0;round<6;round++){await flush();for(const callback of pendingTimers.splice(0)) callback();
  for(const callback of frames.splice(0)) callback(0);}await flush();}
const nextRefreshFrame=async()=>{await flush();assert(frames.length,'fixture expected refresh frame');frames.shift()(0);await flush();};
const settled=promise=>promise.then(()=>({ok:true}),error=>({ok:false,message:error.message}));
const pathOf=request=>new URL(request.path,'http://127.0.0.1/').pathname;
const req=(path,index=0)=>{const matches=requests.filter(r=>pathOf(r)===path);assert(matches[index], 'fixture expected request '+path+' #'+index);return matches[index];};
const ids=()=>requests.filter(r=>/^\/api\/tracks\//.test(r.path)).map(r=>r.path);
function visibleNodes(node=byId('detail')){if(node.hidden||node.getAttribute?.('aria-hidden')==='true'||node.style?.display==='none'||node.style?.visibility==='hidden')return [];return [node,...(node.children||[]).flatMap(c=>visibleNodes(c))];}
const text=()=>visibleNodes().map(n=>n.ownText||'').join(' ');
const statusText=()=>visibleNodes().filter(n=>['status','alert'].includes(n.getAttribute?.('role'))).map(n=>visibleNodes(n).map(c=>c.ownText||'').join(' ')).join(' ');
const loading=()=> /loading|fetching|preparing/i.test(statusText());
const errorVisible=()=> /error|failed|unavailable|unable|could not/i.test(statusText());
// The listener's actions: click a listed track's row, or press Undo or Reset.
function row(id){const found=document.querySelectorAll('#tracks tbody tr').find(item=>item.dataset.trackId===id);assert(found,'a listed row for '+id);return found;}
const select=id=>settled(Promise.resolve(row(id).querySelector('button').onclick()));
const press=name=>settled(Promise.resolve(byId(name).onclick()));
async function accept(id, index=0, epoch=7, history=[], accepted=true) {req('/api/current',index).ok({...snapshot(id,epoch,history),selection_accepted:accepted});await flush();}
async function finish(id,index=0){req('/api/tracks/'+id,index).ok(detail(id));await flush();}
async function paintInitial(){const first=select('OLD');await accept('OLD');await finish('OLD');assert((await first).ok);assert(text().includes('DETAIL OLD'),'fixture renders actual detail metadata');}
async function history(path, id, epoch, items=[]){const operation=press(path.replace("/api/",""));req(path).ok(snapshot(id,epoch,items));await nextRefreshFrame();req('/api/state').ok(snapshot(id,epoch,items));await flush();if(id)await finish(id);assert((await operation).ok);}
// Startup: the listener's state, then the fixture tracks listed by a search; the graph request stays pending.
async function startup(){
  await startupWork(); req('/api/state').ok(snapshot(null)); await startupWork();
  const search=byId('track-search'); search.value='fixture'; search.oninput(); await startupWork();
  req('/api/tracks/summary').ok({tracks:LISTED.map(id=>({handle:id,title:id,artist:'fixture'})),metadata:{track_count:LISTED.length},next_cursor:null});
  await startupWork();
  assert.deepEqual(document.querySelectorAll('#tracks tbody tr').map(r=>r.dataset.trackId),LISTED,'startup lists the fixture tracks');
  assert.equal(seam.snapshot().selectionEpoch,7);
  requests.length=0;
}
"""
