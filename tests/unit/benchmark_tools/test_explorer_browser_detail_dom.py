"""Fast structural DOM policy stubs, NOT rendered-browser acceptance evidence."""
import json
import subprocess
import unittest
from tools.explorer_db_detail_browser import DETAIL_RENDERED, PROBE
from tests.unit.benchmark_tools.test_explorer_browser_native_json_observation import node_executable


class DetailDOMPolicy(unittest.TestCase):
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
