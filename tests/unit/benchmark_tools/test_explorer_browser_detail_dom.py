"""Fast structural DOM policy stubs, NOT rendered-browser acceptance evidence."""
import json
import subprocess
import unittest
from tools.explorer_db_detail_browser import DETAIL_RENDERED
from tests.unit.benchmark_tools.test_explorer_browser_native_json_observation import node_executable


class DetailDOMPolicy(unittest.TestCase):
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
