"""Issue 70 PR6: real asset methods at the fake DOM/ForceGraph boundary.

No rewritten selection/render methods and no WebGL or timing-performance claims.
Each scenario gets a fresh VM and runs against both packaged app.js copies.
"""
import shutil
import subprocess
import unittest
from tests.support.explorer_camera_harness import ASSETS, FIXTURE, ROOT


# Explicit adapter boundary shared by immediate and elapsed-time camera fixtures.


class SelectionCameraIntegrationTests(unittest.TestCase):
    def run_scenario(self, scenario):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Node required: RED must not be accepted via skipped tests')
        for asset in ASSETS:
            with self.subTest(asset=str(asset)):
                script = FIXTURE + scenario + '\n})().then(()=>console.log("SCENARIO_COMPLETED")).catch(error=>{console.error(error);process.exitCode=1;});'
                result = subprocess.run([node, '-e', script, str(asset)], cwd=ROOT,
                                        capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('SCENARIO_COMPLETED', result.stdout,
                              'Node exited before the async scenario completed: ' + result.stderr)

    def test_positioned_result_animates_to_display_position_and_marks_halo(self):
        self.run_scenario(r'''
render(); const original=liveData; const count=replacements; calls.length=0;
await select('a'); tick(); tick();
assert.deepEqual(details,['a'],'selection requests only its detail');
assert.equal(replacements,count,'selection must not replace graphData');
assert.strictEqual(liveData,original,'selection keeps topology and live graph objects');
assertFocus('a');
''')

    def test_latest_selection_before_ready_focuses_only_b_after_initial_frame(self):
        self.run_scenario(r'''
let resolveA;
postHook=id=>id==='a'?new Promise(resolve=>{resolveA=resolve;}):
  Promise.resolve({ok:true,json:async()=>({current_track_id:id,history:[],selection_epoch:0})});
const first=select('a'); await select('b');
resolveA({ok:true,json:async()=>({current_track_id:'a',history:[],selection_epoch:0})});
await first;
assert.deepEqual(details,['b'],'stale A acceptance cannot fetch A detail');
assert.equal(calls.length,0,'pending selection cannot focus before graph exists');
render(); tick(); tick();
assert.equal(calls[0].duration,0,'initial whole-layout framing precedes animated focus');
assertFocus('b');
assert.equal(calls.length,2,'only framing and latest focus, never an A focus');
''')

    def test_replacement_reload_defers_latest_focus_until_new_graph_is_rendered(self):
        self.run_scenario(r'''
render(); const oldGraph=liveData; const before=replacements; calls.length=0;
run("setGraphControlsForTesting({bpmMin:100,bpmMax:140,genres:['ambient']})");
const filters=JSON.stringify(run('getGraphControlsForTesting()'));
let resolveGraph;
graphHook=()=>new Promise(resolve=>{resolveGraph=resolve;});
const reload=run('loadGraph()');
assert.equal(run('graphLoadState.status'),'loading');
await select('a'); await select('b'); tick();
assert.deepEqual(details,['a','b'],'detail stays usable during reload');
assert.strictEqual(liveData,oldGraph,'old instance stays rendered while request pending');
assert.equal(animated().length,0,'latest B focus must not be consumed on old graph during reload');
resolveGraph({ok:true,json:async()=>({dto_version:'mood-axis-graph-indexed-v1',
  selected_mood:'',available_moods:[],
  axis:[{key:'x',label:'Valence',scale:'unit'},{key:'y',label:'Arousal',scale:'unit'},
        {key:'z',label:'BPM',scale:'bpm'}],
  nodes:[['a','A',0.1,0.1,0.2,0.2,120,0.4,null,0.6,[[0,0.8]],[]],
         ['b','B',0.9,0.9,-0.3,-0.3,120,0.4,null,0.6,[[0,0.8]],[]]],
  links:[],unpositioned:[],genre_labels:['ambient'],reason_text:[],
  explanation_table:[],provenance_table:[],metadata:{graph_status:{state:'ready'}}})});
for(let i=0;i<20;i++) await Promise.resolve();
assert.equal(run('graphLoadState.status'),'rendering','replacement waits for a render frame');
await select('a'); await select('b');
assert.equal(animated().length,0,'latest focus also waits across DTO-to-render frame gap');
assert.equal(replacements,before,'new DTO is not rendered yet');
tick(); await reload; tick();
assert.equal(replacements,before+1,'replacement topology rendered on same graph instance');
assert.equal(calls[0].duration,0,'new layout framing precedes selected focus');
assertFocus('b');
assert.notDeepEqual(animated()[0].target,{x:b.fx,y:b.fy,z:b.fz},'focus uses replacement coordinates');
assert.equal(JSON.stringify(run('getGraphControlsForTesting()')),filters,'reload focus preserves active filters');
assert.equal(elements.detail['aria-busy'],'false');
assert.equal(calls.length,2,'one new framing and one latest focus only');
''')

    def test_consumed_focus_preserves_manual_orbit_on_frames_mood_refresh_and_resize(self):
        self.run_scenario(r'''
render(); calls.length=0; await select('a'); tick(); tick(); assertFocus('a');
const before=replacements; calls.length=0;
Object.assign(camera.position,{x:901,y:802,z:703});
Object.assign(controls.target,{x:91,y:82,z:73});
tick(); tick();
const mood=model([a,b].map(n=>({...n,moodScore:{raw:0.8,label:'calm'}})));
render(mood); tick(); for(const callback of resizeCallbacks) callback(); tick();
assert.equal(calls.length,0,'consumed focus never steals manual orbit');
assert.deepEqual(camera.position,{x:901,y:802,z:703});
assert.deepEqual(controls.target,{x:91,y:82,z:73});
assert.equal(replacements,before,'mood-only update does not replace topology');
''')

    def test_missing_unpositioned_and_nonfinite_nodes_show_detail_without_jump(self):
        self.run_scenario(r'''
const bad=node('bad',NaN,0.2,Infinity);
const data=model([a,b,bad]); data.unpositioned=[{track_id:'unpositioned'}];
render(data); calls.length=0;
for(const id of ['missing','unpositioned','bad']) {await select(id); tick();}
assert.deepEqual(details,['missing','unpositioned','bad']);
assert.equal(calls.length,0,'absent or invalid coordinates never move the camera');
assert.equal(elements.detail['aria-busy'],'false','detail completes independently');
''')

    def test_hidden_node_preserves_filters_and_still_loads_detail_without_focus(self):
        self.run_scenario(r'''
context.fullModel=model();
run("setGraphControlsForTesting({bpmMin:130,bpmMax:150,genres:['ambient']})");
const filters=JSON.stringify(run('getGraphControlsForTesting()'));
const filtered=run('applyMoodGraphFilters(fullModel,getGraphControlsForTesting())');
assert.equal(filtered.nodes.length,0,'fixture proves the selected node is hidden');
render(filtered,context.fullModel); calls.length=0; await select('a'); tick(); tick();
assert.deepEqual(details,['a'],'hidden nodes still get independent current detail');
assert.equal(calls.length,0,'hidden nodes must not trigger focus or clear filters');
assert.equal(JSON.stringify(run('getGraphControlsForTesting()')),filters);
assert.equal(replacements,1,'selection cannot repopulate filtered topology');
''')

    def test_graph_click_uses_selection_detail_and_immediate_translation(self):
        self.run_scenario(r'''
render(); calls.length=0;
assert.equal(typeof clickHandler,'function','real renderMap wires graph picking');
const before={...camera.position}, target={...controls.target};
const pending=clickHandler(liveData.nodes.find(n=>n.id==='b'));
assert.deepEqual(controls.target,{x:b.fx,y:b.fy,z:b.fz});
for(const axis of ['x','y','z'])
  assert.equal(camera.position[axis],b['f'+axis]+(before[axis]-target[axis]));
const centered={...camera.position}, count=calls.length;
await pending; tick(); tick();
assert.deepEqual(details,['b']); assertHalo('b');
assert.deepEqual(camera.position,centered); assert.equal(calls.length,count,'acceptance does not replay focus');
''')

    def test_undo_replaces_pending_focus_with_authoritative_history_selection(self):
        self.run_scenario(r'''
await select('a');
historyHook=()=>({current_track_id:'b',history:[],selection_epoch:0});
await history('/api/undo');
assert.deepEqual(details,['a','b'],'undo keeps selected detail behavior');
render(); tick(); tick(); assertFocus('b');
assert.equal(calls.length,2,'no stale pending A focus after undo');
''')

    def test_reset_cancels_pending_focus_and_late_selection_acceptance(self):
        self.run_scenario(r'''
let resolveA;
postHook=()=>new Promise(resolve=>{resolveA=resolve;});
const first=select('a');
historyHook=()=>({current_track_id:null,history:[],selection_epoch:1});
await history('/api/reset');
resolveA({ok:true,json:async()=>({current_track_id:'a',history:[],selection_epoch:0})});
await first;
render(); tick(); tick();
assert.deepEqual(details,[],'reset invalidates stale acceptance and detail');
assert.equal(run('getStateForTesting().current_track_id'),null);
assert.equal(run('getStateForTesting().selection_epoch'),1);
assert.equal(calls.length,1,'only initial framing after reset');
assert.equal(animated().length,0,'no stale selected focus after reset');
assert.ok(!scene.children.some(c=>c.userData?.role==='selected-node-halo'));
''')

    def test_rejected_selection_reconciles_pending_focus_to_authoritative_node(self):
        self.run_scenario(r'''
postHook=()=>Promise.resolve({ok:true,json:async()=>({current_track_id:'b',history:[],
  selection_epoch:0,selection_accepted:false})});
await select('a');
assert.deepEqual(details,['b'],'rejected A reconciles to authoritative B detail');
render(); tick(); tick(); assertFocus('b');
assert.equal(calls.length,2,'initial frame then authoritative focus, never rejected A');
''')

    def test_control_without_selection_frames_once_and_keeps_manual_camera(self):
        self.run_scenario(r'''
render(); assert.equal(calls.length,1); assert.equal(calls[0].duration,0);
const before=replacements; calls.length=0;
Object.assign(camera.position,{x:900,y:800,z:700});
Object.assign(controls.target,{x:90,y:80,z:70});
render(); tick(); tick(); for(const callback of resizeCallbacks) callback();
assert.equal(calls.length,0,'unchanged graph does not reframe manual orbit');
assert.equal(replacements,before); assert.deepEqual(details,[]);
assert.deepEqual(camera.position,{x:900,y:800,z:700});
assert.deepEqual(controls.target,{x:90,y:80,z:70});
''')


if __name__ == '__main__':
    unittest.main()
