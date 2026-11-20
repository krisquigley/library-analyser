"""The selection and detail tests' shared Node harness for the Explorer app (#146)."""
from pathlib import Path
import os
import shutil
from tests.support.explorer_app_bundle import explorer_app_script


ROOT = Path(__file__).resolve().parents[2]


ASSETS = tuple(explorer_app_script(ROOT / package / "frameworks/explorer/assets/app.js")
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
async function history(path, id, epoch, items=[]){const operation=settled(context.applyHistorySelection(path.replace("/api/","")));req(path).ok(snapshot(id,epoch,items));await nextRefreshFrame();req('/api/state').ok(snapshot(id,epoch,items));await flush();if(id)await finish(id);assert((await operation).ok);}
"""
