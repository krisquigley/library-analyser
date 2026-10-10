"""Fast structural DOM policy stubs, NOT rendered-browser acceptance evidence."""
import json
import subprocess
import unittest
from tools.explorer_db_detail_browser import DETAIL_RENDERED, PROBE, WRAP_DETAIL
from tests.unit.benchmark_tools.test_explorer_browser_native_json_observation import node_executable


class DetailDOMPolicy(unittest.TestCase):
    def test_frame_evidence_rejects_replaced_detached_and_moved_nodes(self):
        script = r'''
const vm=require('vm'), wrap=WRAP;
const make=(tagName,textContent='')=>({tagName,textContent,isConnected:true,
 checkVisibility:()=>true,getBoundingClientRect:()=>({width:10,height:10,left:1,right:11,top:1,bottom:11}),
 matches:()=>true});
const fields=()=>{const node=make('DIV','private genuine');node.children=[make('SECTION')];return node;};
const root=()=>{const node=make('DIV');node.children=[make('H3','Current Track'),fields()];
 node.children[1].parentElement=node;node.getAttribute=()=> 'false';node.querySelector=()=>null;return node;};
const results=[];
for(const fault of ['pristine','replaced-fields','replaced-root','detached-root','moved-fields']){
 let live=root(), rendered, compared;const queue=[],s={sequence:1,intended_handle:'private-intended'};
 global.document={getElementById:()=>live,querySelectorAll:()=>[{dataset:{trackId:s.intended_handle}}]};
 global.innerWidth=640;global.innerHeight=480;
 global.requestAnimationFrame=callback=>queue.push(callback);
 global.window={__dbBridge:{selections:[s]},__dbDetailContentMatches:(sequence,node)=>{compared=node;return true;}};
 global.renderDetailLoading=()=>{};
 global.renderDetail=()=>{
  rendered=fields();rendered.parentElement=live;live.children[1]=rendered;
  requestAnimationFrame(()=>{
   if(fault==='replaced-fields'){rendered.isConnected=false;live.children[1]=fields();live.children[1].parentElement=live;}
   if(fault==='replaced-root'){live.isConnected=false;rendered.isConnected=false;live=root();}
   if(fault==='detached-root'){live.isConnected=false;rendered.isConnected=false;}
   if(fault==='moved-fields'){rendered.parentElement=root();}
  });
 };
 vm.runInThisContext('('+wrap+')()');renderDetail();while(queue.length)queue.shift()();
 results.push({fault,presented:s.detail_presented,ready:s.detail_dom_ready_ms!=null,
  frame:s.detail_next_frame_ms!=null,comparedLive:compared===live.children[1],identity:s.dom_identity_matches});
}
console.log(JSON.stringify(results));
'''.replace('WRAP', json.dumps(WRAP_DETAIL))
        result = subprocess.run([node_executable(), '-e', script], capture_output=True,
                                text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('private', result.stdout)
        observations = json.loads(result.stdout)
        for observation in observations:
            with self.subTest(fault=observation['fault']):
                valid = observation['fault'] == 'pristine'
                self.assertIs(observation['presented'], valid)
                self.assertIs(observation['ready'], valid)
                self.assertIs(observation['frame'], valid)
                self.assertIs(observation['comparedLive'], True)
                self.assertIsNone(observation['identity'])

    def test_expected_content_is_private_snapshot_of_consumed_response(self):
        script = r'''
const vm=require('vm');
const make=()=>({children:[],append(value){this.children.push(value);},
 isEqualNode(other){return JSON.stringify(this.children)===JSON.stringify(other.children);}});
global.window={fetch:async()=>({ok:true,status:200,text:async()=>JSON.stringify({
 handle:'private-handle',metadata:{title:'private-original'},fields:{bpm:{value:123}}})})};
global.location={href:'http://localhost/'};
global.document={addEventListener(){},createElement:make};
global.renderTrackMetadata=value=>JSON.parse(JSON.stringify(value));
global.renderDetailField=(name,value)=>({name,...value});
vm.runInThisContext(PROBE);
(async()=>{
 const d=window.__dbBridge,selection={sequence:1,intended_handle:'private-handle'};
 d.selections.push(selection);
 const response=await window.fetch('/api/tracks/private-handle');const value=await response.json();
 value.metadata.title='private-fabricated';value.fields={};
 const wrong=make();wrong.append(renderTrackMetadata(value.metadata));
 const mismatch=window.__dbDetailContentMatches(1,wrong);
 const missing=window.__dbDetailContentMatches(1,wrong);
 selection.sequence=2;await (await window.fetch('/api/tracks/private-handle')).json();
 const actual=make();actual.append({title:'private-original'});actual.append({name:'bpm',value:123});
 const match=window.__dbDetailContentMatches(2,actual);
 selection.sequence=3;await (await window.fetch('/api/tracks/private-wrong')).json();
 const wrongRequest=window.__dbDetailContentMatches(3,actual);
 const privateSnapshotNotExported=!JSON.stringify(d).includes('private-original')&&!JSON.stringify(d).includes('private-fabricated');
 console.log(JSON.stringify({mismatch,missing,match,wrongRequest,privateSnapshotNotExported}));
})().catch(()=>process.exit(1));
'''.replace('PROBE', json.dumps(PROBE.read_text()))
        result = subprocess.run([node_executable(), '-e', script], capture_output=True,
                                text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), dict(mismatch=False, missing=False,
            match=True, wrongRequest=False, privateSnapshotNotExported=True))

    def test_fresh_structure_bound_to_intent_exports_only_boolean(self):
        script = r'''
const check=CHECK;
const make=(tagName,textContent='')=>({tagName,textContent,checkVisibility:()=>true,
 getBoundingClientRect:()=>({width:10,height:10,left:1,right:11,top:1,bottom:11}),matches:()=>true});
const metadata=make('SECTION','private metadata'),heading=make('H3','Current Track');
const fields=make('DIV','private metadata');fields.children=[metadata];
const root=make('DIV');root.children=[heading,fields];root.getAttribute=()=> 'false';root.querySelector=()=>null;
const row={dataset:{trackId:'private-intended'}};
global.document={getElementById:()=>root,querySelectorAll:()=>[row]};global.innerWidth=640;global.innerHeight=480;
const valid=check('private-intended');
row.dataset.trackId='private-stale';const wrongRow=check('private-intended');row.dataset.trackId='private-intended';
fields.getBoundingClientRect=()=>({width:10,height:10,left:1,right:11,top:10000,bottom:10010});const offscreen=check('private-intended');
fields.getBoundingClientRect=()=>({width:10,height:10,left:1,right:11,top:1,bottom:11});
const unchanged=check('private-intended',fields),staleNode=check('private-intended',null,fields);
const staleClone=check('private-intended',null,{},'private metadata','previous-intended');
root.children=[make('P','Loading')];const loading=check('private-intended');
console.log(JSON.stringify({valid,wrongRow,offscreen,unchanged,staleNode,staleClone,loading}));
'''.replace('CHECK', DETAIL_RENDERED)
        result = subprocess.run([node_executable(), '-e', script], capture_output=True,
                                text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('private', result.stdout)
        self.assertEqual(json.loads(result.stdout), dict(valid=True, wrongRow=False,
            offscreen=False, unchanged=False, staleNode=False, staleClone=False, loading=False))
