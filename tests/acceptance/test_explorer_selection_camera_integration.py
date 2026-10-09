"""Issue 70 PR6: real asset methods at the fake DOM/ForceGraph boundary.

No rewritten selection/render methods and no WebGL or timing-performance claims.
Each scenario gets a fresh VM and runs against both packaged app.js copies.
"""
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = tuple(ROOT / package / 'frameworks/explorer/assets/app.js'
               for package in ('music_explorer', 'music_analyzer'))

FIXTURE = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const frames = [], calls = [], requests = [], details = [];
class Element {
  constructor(tag='div') { this.tagName=tag.toUpperCase(); this.children=[];
    this.style={}; this.dataset={}; this.clientWidth=800; this.clientHeight=600; }
  append(...children) { for(const child of children) {this.children.push(child); child.parentElement=this;} }
  replaceChildren(...children) { this.children=[]; this.append(...children); }
  setAttribute(key,value) {this[key]=value;}
  removeAttribute(key) {delete this[key];}
  getBoundingClientRect() {return {width:800,height:600,left:0,top:0};}
}
const elements = {graph3d:new Element(), detail:new Element()};
const document = {getElementById:id=>elements[id]||null,
  createElement:tag=>new Element(tag), querySelectorAll:()=>[]};
const scene = {children:[], add(child){this.children.push(child); child.parent=this;},
  remove(child){this.children=this.children.filter(c=>c!==child); child.parent=null;}};
class Geometry {constructor(radius){this.parameters={radius};} dispose(){} }
class Material {constructor(props={}){Object.assign(this,props);} dispose(){} }
class Mesh {
  constructor(geometry,material) {this.geometry=geometry; this.material=material; this.userData={};
    this.position={x:0,y:0,z:0,set(x,y,z){Object.assign(this,{x,y,z});}};
    this.scale={setScalar(value){this.value=value;}};}
}
let liveData={nodes:[],links:[]}, replacements=0;
const camera = {fov:50,position:{x:500,y:400,z:300}};
const controls = {target:{x:0,y:0,z:0}};
const graph = new Proxy({}, {get(_target,key) {
  if(key==='scene') return ()=>scene;
  if(key==='camera') return ()=>camera;
  if(key==='controls') return ()=>controls;
  if(key==='graph2ScreenCoords') return ()=>({x:400,y:300});
  if(key==='graphData') return data=>{
    if(!data) return liveData;
    liveData=data; replacements++;
    scene.children=scene.children.filter(c=>!c.userData?.trackId);
    for(const node of data.nodes) {
      const mesh=new Mesh(new Geometry(4),new Material()); mesh.userData.trackId=node.id;
      mesh.position.set(node.fx,node.fy,node.fz); scene.add(mesh);
    }
    return graph;
  };
  if(key==='cameraPosition') return (position,target,duration)=>{
    if(!position) return {...camera.position};
    calls.push({position:{...position},target:{...target},duration});
    Object.assign(camera.position,position); Object.assign(controls.target,target);
    return graph;
  };
  if(key==='onNodeClick') return fn=>{clickHandler=fn; return graph;};
  return ()=>graph;
}});
const resizeCallbacks=[];
class ResizeObserver {constructor(callback){resizeCallbacks.push(callback);} observe(){} }
let postHook=null, historyHook=null, authoritativeSnapshot={current_track_id:null,history:[],selection_epoch:0};
let clickHandler=null;
const context=vm.createContext({console,URLSearchParams,setTimeout,clearTimeout,
  requestAnimationFrame:fn=>{frames.push(fn);return frames.length;},ResizeObserver,
  ForceGraph3D:()=>()=>graph,
  fetch:async(path,options)=>{
    requests.push({path,options});
    if(path==='/api/current') {
      const id=JSON.parse(options.body).track_id;
      if(postHook) return postHook(id);
      return {ok:true,json:async()=>({current_track_id:id,history:[],selection_epoch:0})};
    }
    if(path==='/api/undo'||path==='/api/reset') {
      assert.equal(options.method,'POST');
      authoritativeSnapshot=historyHook(path);
      return {ok:true,json:async()=>authoritativeSnapshot};
    }
    if(path==='/api/state') return {ok:true,json:async()=>authoritativeSnapshot};
    if(path.startsWith('/api/tracks/')) {
      const id=decodeURIComponent(path.slice('/api/tracks/'.length)); details.push(id);
      return {ok:true,json:async()=>({metadata:{title:'Detail '+id},fields:{}})};
    }
    throw new Error('Unexpected fixture request: '+path);
  }});
// Compile the complete unmodified asset; no document yet means no startup I/O.
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context,{filename:process.argv[1]});
context.document=document;
const run=code=>vm.runInContext(code,context);
const select=id=>run(`setCurrent(${JSON.stringify(id)})`);
function node(id,x=0.25,y=-0.4,z=0.6) {
  return {id,label:id,x:x*200,y:y*200,z:z*200,fx:x*200,fy:y*200,fz:z*200,color:'#123456',
    bpm:120,genres:[['ambient',0.8]],moodScore:null,
    axis:{x:{raw:x,normalized:x,scale:'test'},y:{raw:y,normalized:y,scale:'test'},
      z:{raw:z,normalized:z,label:'test',scale:'test'}}};
}
const a=node('a'), b=node('b',-0.7,0.8,0.2);
function model(nodes=[a,b]) {return {nodes,links:[],unpositioned:[],availableMoods:[],
  selectedMood:'',metadata:{},genreOptions:['ambient']};}
function render(data=model(),full=data) {
  context.fixtureModel=data; context.fixtureFullModel=full;
  run("graphLoadState={...graphLoadState,status:'rendering'}; setGraphModelForTesting(fixtureFullModel); setVisibleGraphForTesting(fixtureModel); renderMap(fixtureModel); graphLoadState={...graphLoadState,status:'ready'}");
}
function tick() {const pending=frames.splice(0); for(const callback of pending) callback();}
async function history(path) {
  const promise=run(`applyHistorySelection(${JSON.stringify(path)})`);
  // Flush the bounded microtask/nextFrame chain used by real refresh().
  for(let i=0;i<20;i++) {await Promise.resolve(); tick();}
  await promise;
}
function animated() {return calls.filter(c=>c.duration>0);}
function assertHalo(id) {
  const expected=liveData.nodes.find(n=>n.id===id);
  const halo=scene.children.find(c=>c.userData?.role==='selected-node-halo');
  assert.ok(halo,'visible selected-node halo'); assert.equal(halo.userData.trackId,id);
  assert.equal(halo.material.depthTest,false,'halo remains visible through nearby nodes');
  assert.deepEqual({x:halo.position.x,y:halo.position.y,z:halo.position.z},
    {x:expected.fx,y:expected.fy,z:expected.fz});
}
function assertFocus(id) {
  assertHalo(id);
  const focus=animated();
  assert.equal(focus.length,1,'one animated cameraPosition for the latest available selection');
  const expected=liveData.nodes.find(n=>n.id===id);
  assert.deepEqual(focus[0].target,{x:expected.fx,y:expected.fy,z:expected.fz},
    'look-at uses display coordinates, not raw normalized coordinates');
  for(const point of [focus[0].position,focus[0].target])
    assert.ok(['x','y','z'].every(axis=>Number.isFinite(point[axis])),'camera coordinates finite');
  assert.ok(Number.isFinite(focus[0].duration)&&focus[0].duration>0,'positive smooth duration');
  assert.notDeepEqual(focus[0].position,focus[0].target,'nonzero useful camera distance');
}
(async()=>{
'''


class SelectionCameraIntegrationTests(unittest.TestCase):
    def run_scenario(self, scenario):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Node required: RED must not be accepted via skipped tests')
        for asset in ASSETS:
            with self.subTest(asset=str(asset.relative_to(ROOT))):
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

    def test_graph_click_uses_selection_detail_and_animated_focus(self):
        self.run_scenario(r'''
render(); calls.length=0;
assert.equal(typeof clickHandler,'function','real renderMap wires graph picking');
await clickHandler(liveData.nodes.find(n=>n.id==='b')); tick(); tick();
assert.deepEqual(details,['b']); assertFocus('b');
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

    def test_origin_selection_keeps_detail_without_invalid_camera_jump(self):
        self.run_scenario(r'''
render(model([a,node('origin',0,0,0)])); calls.length=0;
await select('origin'); tick(); tick();
assert.deepEqual(details,['origin']);
assert.equal(calls.length,0,'origin has no direction for selection zoom: no invalid jump');
assert.equal(elements.detail['aria-busy'],'false');
''')

    def test_control_selected_halo_and_mood_resize_fixture_preserve_orbit(self):
        """Control validates the post-focus fixture separately from its RED precondition."""
        self.run_scenario(r'''
run("setStateForTesting({current_track_id:'a'})"); render(); tick(); assertHalo('a');
const before=replacements; calls.length=0;
Object.assign(camera.position,{x:901,y:802,z:703});
Object.assign(controls.target,{x:91,y:82,z:73});
render(model([a,b].map(n=>({...n,moodScore:{raw:0.8,label:'calm'}}))));
tick(); tick(); for(const callback of resizeCallbacks) callback(); tick();
assertHalo('a'); assert.equal(calls.length,0);
assert.equal(replacements,before);
assert.deepEqual(camera.position,{x:901,y:802,z:703});
assert.deepEqual(controls.target,{x:91,y:82,z:73});
''')

    def test_control_detail_is_usable_while_graph_is_unavailable(self):
        self.run_scenario(r'''
await select('a'); await select('b');
assert.deepEqual(details,['a','b']);
assert.equal(calls.length,0,'detail requires no graph instance');
assert.equal(elements.detail['aria-busy'],'false');
assert.equal(requests.filter(r=>r.path.startsWith('/api/tracks/')).length,2);
assert.equal(requests.filter(r=>r.path.includes('graph')).length,0);
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
