"""The camera tests' shared Node harness for the Explorer app: fixture, vendored graph library and recorded inputs (#146).

The page starts as in a browser, at ``?diagnostics``. A test shows a graph by answering the page's graph
request (``render``), chooses a listed track by clicking its row (``select``), uses undo and reset by their
buttons (``history``) and picks a node through the 3D graph's click handler. The page is observed through its
diagnostics seam (``seam``), the fake DOM, its requests and the 3D graph's boundary.
"""
from pathlib import Path
from tests.support.explorer_app_bundle import explorer_app_script
from tests.support.explorer_page_harness import FAKE_DOM


ROOT = Path(__file__).resolve().parents[2]


ASSETS = tuple(explorer_app_script(ROOT / package / 'frameworks/explorer/assets/app.js')
               for package in ('music_explorer', 'music_analyzer'))


FRAME_CLOCK_SEAM = "requestAnimationFrame:fn=>{frames.push(fn);return frames.length;},performance:{now:()=>fixtureClock},ResizeObserver,"


def replace_fixture_seam(fixture, seam, replacement):
    matches = fixture.count(seam)
    if matches != 1:
        raise ValueError(f'Camera fixture seam must occur exactly once; found {matches}: {seam}')
    return fixture.replace(seam, replacement, 1)


FIXTURE = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const frames = [], calls = [], requests = [], details = [];
let fixtureClock=0;
''' + FAKE_DOM + r'''
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
    if(cameraFailure) throw cameraFailure;
    if(!position) return {...camera.position};
    calls.push({position:{...position},target:{...target},duration,at:fixtureClock});
    Object.assign(camera.position,position); Object.assign(controls.target,target);
    return graph;
  };
  if(key==='onNodeClick') return fn=>{clickHandler=fn; return graph;};
  return ()=>graph;
}});
const resizeCallbacks=[];
class ResizeObserver {constructor(callback){resizeCallbacks.push(callback);} observe(){} }
let graphHook=null, answerGraph=null, cameraFailure=null;
let postHook=null, historyHook=null, historyGate=null, authoritativeSnapshot={current_track_id:null,history:[],selection_epoch:0};
let clickHandler=null;
// The tracks a test chooses from the list; their rows are listed once, by a real search, at startup.
const LISTED=['a','b','unpositioned','missing','bad'];
const pendingTimers=[];
const storage=new Map();
const context=vm.createContext({console,URL,URLSearchParams,document,
  location:{search:'?diagnostics',href:'http://127.0.0.1/?diagnostics'},
  sessionStorage:{getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,String(value))},
  setTimeout:callback=>{pendingTimers.push(callback);return pendingTimers.length;},clearTimeout(){},
  requestAnimationFrame:fn=>{frames.push(fn);return frames.length;},performance:{now:()=>fixtureClock},ResizeObserver,
  ForceGraph3D:()=>()=>graph,
  fetch:async(path,options={})=>{
    requests.push({path,options});
    const url=new URL(path,'http://127.0.0.1/');
    if(url.pathname==='/api/mood-axis-graph') return graphHook?graphHook():new Promise(resolve=>{answerGraph=resolve;});
    if(url.pathname==='/api/tracks/summary')
      return {ok:true,json:async()=>({tracks:LISTED.map(id=>({handle:id,title:id,artist:'fixture'})),metadata:{track_count:LISTED.length},next_cursor:null})};
    if(path==='/api/current') {
      const id=JSON.parse(options.body).track_id;
      if(postHook) return postHook(id);
      return {ok:true,json:async()=>({current_track_id:id,history:[],selection_epoch:0})};
    }
    if(path==='/api/undo'||path==='/api/reset') {
      assert.equal(options.method,'POST');
      if(historyGate) return historyGate(path);
      authoritativeSnapshot=historyHook(path);
      return {ok:true,json:async()=>authoritativeSnapshot};
    }
    if(path==='/api/state') return {ok:true,json:async()=>authoritativeSnapshot};
    if(path.startsWith('/api/tracks/')) {
      const id=decodeURIComponent(path.slice('/api/tracks/'.length)); details.push(id);
      return {ok:true,json:async()=>({handle:id,metadata:{common:[['title','Detail '+id]],tags:[]},fields:{}})};
    }
    throw new Error('Unexpected fixture request: '+path);
  }});
// The complete unmodified asset starts as in a browser, at ?diagnostics; tests observe it through its seam.
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context,{filename:process.argv[1]});
const seam=context.explorerDiagnostics;
const flush=async()=>{for(let i=0;i<60;i++) await Promise.resolve();};
// Startup's own frames and timers, run without moving the camera clock.
async function startupWork(){for(let round=0;round<6;round++){await flush();for(const callback of pendingTimers.splice(0)) callback();
  for(const callback of frames.splice(0)) if(callback) callback(fixtureClock);}await flush();}
async function startup(){
  await startupWork();
  const search=byId('track-search'); search.value='fixture'; search.oninput();
  await startupWork();
  assert.deepEqual(document.querySelectorAll('#tracks tbody tr').map(row=>row.dataset.trackId),LISTED,'startup lists the fixture tracks');
  requests.length=0;
}
// Display coordinates are the page's own: normalized position times the graph scale, computed as it does.
const DISPLAY=value=>value*180*2;
function node(id,x=0.25,y=-0.4,z=0.6) {
  const [nx,ny,nz]=[x,y,z].map(value=>value*200/360);
  return {id,label:id,x:DISPLAY(nx),y:DISPLAY(ny),z:DISPLAY(nz),fx:DISPLAY(nx),fy:DISPLAY(ny),fz:DISPLAY(nz),color:'#123456',
    bpm:120,genres:[['ambient',0.8]],moodScore:null,normalized:{x:nx,y:ny,z:nz},
    axis:{x:{raw:x,normalized:nx,scale:'test'},y:{raw:y,normalized:ny,scale:'test'},
      z:{raw:z,normalized:nz,label:'test',scale:'test'}}};
}
const a=node('a'), b=node('b',-0.7,0.8,0.2);
function model(nodes=[a,b]) {return {nodes,links:[],unpositioned:[],availableMoods:[],
  selectedMood:'',metadata:{},genreOptions:['ambient']};}
// A node a test moved by hand keeps its display coordinate: its normalized value is derived from it.
const normalizedOf=(n,key)=>DISPLAY(n.normalized?.[key])===n['f'+key]?n.normalized[key]:n['f'+key]/360;
function graphBody(data) {
  const index=new Map(data.nodes.map((n,i)=>[n.id,i]));
  return {dto_version:'mood-axis-graph-indexed-v1',selected_mood:data.selectedMood||'',available_moods:data.availableMoods||[],
    axis:[{key:'x',label:'X',scale:'test'},{key:'y',label:'Y',scale:'test'},{key:'z',label:'Z',scale:'test'}],
    nodes:data.nodes.map(n=>[n.id,n.label,n.axis?.x?.raw??0,normalizedOf(n,'x'),n.axis?.y?.raw??0,normalizedOf(n,'y'),
      n.axis?.z?.raw??0,normalizedOf(n,'z'),n.bpm??120,null,[[0,0.8]],[]]),
    links:(data.links||[]).map(l=>[index.get(l.source?.id??l.source),index.get(l.target?.id??l.target),l.score??0.5]),
    unpositioned:(data.unpositioned||[]).map(u=>[u.id??u.track_id,u.label??u.id??u.track_id,[]]),
    genre_labels:['ambient'],reason_text:[],explanation_table:[],provenance_table:[],metadata:{graph_status:{state:'ready'}}};
}
// The page receives this graph: it answers the page's graph request, asking for a reload first if none is
// waiting. The page builds the graph's model and waits for a frame to draw it.
async function receiveGraph(data=model()) {
  if(!answerGraph) { byId('reload-graph').onclick(); await flush(); }
  assert.ok(answerGraph,'the page asked for the graph');
  const answer=answerGraph; answerGraph=null;
  answer({ok:true,status:200,json:async()=>graphBody(data)});
  await flush();
}
// The page shows this graph: it receives it, then draws it in the next frame.
async function render(data=model()) {
  await receiveGraph(data);
  for(const callback of frames.splice(0)) if(callback) callback(fixtureClock);
  await flush();
  assert.equal(seam.snapshot().graphStatus,'ready','the page shows the graph');
}
// Choosing a listed track: the listener clicks its row; the page posts the choice at once.
function row(id){const found=document.querySelectorAll('#tracks tbody tr').find(item=>item.dataset.trackId===id);assert.ok(found,'a listed row for '+id);return found;}
const select=id=>Promise.resolve(row(id).querySelector('button').onclick());
function tick() {fixtureClock+=700; const pending=frames.splice(0); for(const callback of pending) callback(fixtureClock);}
async function history(path) {
  const promise=Promise.resolve(byId(path==='/api/undo'?'undo':'reset').onclick());
  // Flush the bounded microtask/nextFrame chain used by real refresh().
  for(let i=0;i<20;i++) {await Promise.resolve(); tick();}
  await promise;
}
function animated() {return calls.filter(c=>liveData.nodes.some(n=>c.target.x===n.fx&&c.target.y===n.fy&&c.target.z===n.fz));}
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
  assert.equal(focus.length,1,'one completed adapter focus for the latest available selection');
  const expected=liveData.nodes.find(n=>n.id===id);
  assert.deepEqual(focus[0].target,{x:expected.fx,y:expected.fy,z:expected.fz},
    'look-at uses display coordinates, not raw normalized coordinates');
  for(const point of [focus[0].position,focus[0].target])
    assert.ok(['x','y','z'].every(axis=>Number.isFinite(point[axis])),'camera coordinates finite');
  assert.equal(focus[0].duration,0,'adapter must not create uncancellable vendor tweens');
  assert.notDeepEqual(focus[0].position,focus[0].target,'nonzero useful camera distance');
  const length=Math.hypot(expected.fx,expected.fy,expected.fz);
  for(const axis of ['x','y','z']) {
    const coordinate=expected['f'+axis];
    assert.ok(Math.abs(focus[0].position[axis]-(coordinate+100*coordinate/length))<1e-9,
      'final camera position retains the 100-unit display-space radial offset');
  }
}
(async()=>{
await startup();
'''


VENDOR = r'''
const vendor = (() => {
  const fs = require('node:fs'), vm = require('node:vm');
  const path = require('node:path').join(require('node:path').dirname(process.argv[1]),
    'vendor/3d-force-graph/3d-force-graph.min.js');
  let source = fs.readFileSync(path, 'utf8').trimEnd();
  const start = source.indexOf('cameraPosition:function(e,t,n,i)');
  const end = source.indexOf(',zoomToFit:', start);
  if (start < 0 || end < 0) throw new Error('Bundled camera seam changed; review harness');
  const method = source.slice(start + 'cameraPosition:'.length, end);
  const boundary = 'return Ok});';
  if (!source.endsWith(boundary)) throw new Error('Bundled closure changed; review harness');
  source = source.slice(0, -boundary.length) +
    `globalThis.cameraTestExports={Group:oO,THREE:Ak,cameraPosition:${method}};` + boundary;
  let now = 0;
  const context = vm.createContext({console, setTimeout, clearTimeout, setInterval,
    clearInterval, window:{}, performance:{now:()=>now}});
  vm.runInContext(source, context, {filename:path});
  return {...context.cameraTestExports, setTime:value=>{now=value;}};
})();
let now=0, frameId=0;
const cancelledFrames=new Set();
const vendorCamera=new vendor.THREE.PerspectiveCamera();
vendorCamera.position.set(500,400,300);
// THREE camera inherits the bundled event dispatcher used by controls; no renderer needed.
const vendorControls=Object.assign(new vendor.THREE.PerspectiveCamera(),
  {enabled:true,target:new vendor.THREE.Vector3()});
const vendorState={initialised:true,camera:vendorCamera,controls:vendorControls,
  tweenGroup:new vendor.Group()};
'''


def real_vendor_fixture():
    fixture = replace_fixture_seam(FIXTURE,
        "const camera = {fov:50,position:{x:500,y:400,z:300}};\nconst controls = {target:{x:0,y:0,z:0}};",
        "const camera=vendorCamera; camera.fov=50; const controls=vendorControls;")
    fixture = replace_fixture_seam(fixture,
        "Object.assign(camera.position,position); Object.assign(controls.target,target);",
        "vendor.cameraPosition(vendorState,position,target,duration);")
    fixture = replace_fixture_seam(fixture,
        FRAME_CLOCK_SEAM,
        "performance:{now:()=>now}, requestAnimationFrame:fn=>{const id=++frameId;\n"
        "    frames.push(time=>{if(!cancelledFrames.has(id)) fn(time);});return id;},\n"
        "  cancelAnimationFrame:id=>cancelledFrames.add(id),ResizeObserver,")
    fixture = replace_fixture_seam(fixture,
        "function tick() {fixtureClock+=700; const pending=frames.splice(0); for(const callback of pending) callback(fixtureClock);}",
        "function tick() {const pending=frames.splice(0); for(const callback of pending) if(callback) callback(now);}\n"
        "function advance(time) {now=time; vendor.setTime(time); tick(); vendorState.tweenGroup.update(time);}\n"
        "function pose() {return {position:{x:camera.position.x,y:camera.position.y,z:camera.position.z},\n"
        "  target:{x:controls.target.x,y:controls.target.y,z:controls.target.z}};}")
    return VENDOR + fixture


def trackball_fixture():
    fixture = real_vendor_fixture()
    replacements = (
        ('Group:oO,THREE:Ak,', 'Group:oO,THREE:Ak,Trackball:cU,'),
        ('const vendorControls=Object.assign(new vendor.THREE.PerspectiveCamera(),\n'
         '  {enabled:true,target:new vendor.THREE.Vector3()});',
         'const vendorControls=new vendor.Trackball(vendorCamera);'),
        ('vendorState.tweenGroup.update(time);}',
         'vendorState.tweenGroup.update(time); controls.update();}'),
    )
    for before, after in replacements:
        if fixture.count(before) != 1:
            raise AssertionError('Trackball fixture seam changed: ' + before)
        fixture = fixture.replace(before, after, 1)
    return fixture


FINITE_WHEEL_PAN = r'''
function wheelAndPanToRadius(radius) {
  controls.target.set(0,0,0);
  camera.position.set(500,500,500);
  camera.up.set(0,1,0);
  controls.update();
  let count=0;
  for(;count<10000;count++) {
    controls._onMouseWheel({deltaMode:0,deltaY:120,preventDefault(){}});
    controls.update();
    assert.ok(camera.position.toArray().every(Number.isFinite),'actual wheel remains finite');
    if(Math.hypot(...camera.position.toArray())>=radius) break;
  }
  assert.ok(count<10000,'bounded wheel reproduction reaches requested finite scale');
  // Finish wheel damping before panning, using only the actual bundled update.
  for(let i=0;i<200;i++) controls.update();
  Object.assign(controls.screen,{left:0,top:0,width:800,height:600});
  controls._onMouseDown({button:2,pageX:400,pageY:300});
  controls._onMouseMove({pageX:500,pageY:350});
  controls.update();
  controls._onMouseUp();
  for(let i=0;i<200;i++) controls.update();
  // Public static mode flushes residual pan damping without replacing controls.
  controls.staticMoving=true; controls.update(); controls.staticMoving=false;
  assert.ok([...camera.position.toArray(),...controls.target.toArray(),
    ...camera.up.toArray(),...camera.quaternion.toArray()].every(Number.isFinite),
    'actual wheel and pan produce an entirely finite rendered start pose');
  assert.ok(Math.hypot(...controls.target.toArray())>radius/100,
    'actual right-button pan moves target to the huge finite scale');
  assert.ok(Number.isFinite(camera.position.distanceTo(controls.target)),
    'astronomical input stops before bundled squared-radius overflow');
  console.log('ACTUAL_FINITE_WHEEL_PAN',count,pose());
}
'''


INPUTS = r'''
function manualStart() {
  controls.target.set(120,-80,30);
  camera.position.set(400,-240,180);
  camera.up.set(0.2,1,0.3).normalize();
  controls.minDistance=0.25; controls.maxDistance=2000;
  Object.assign(controls.screen,{left:0,top:0,width:800,height:600});
  controls.update();
}
function unflushedWheel() {
  controls._onMouseWheel({deltaMode:0,deltaY:120,preventDefault(){}});
  controls.update();
  // No further update: dynamic zoom remains outstanding at selection time.
}
function unflushedPan() {
  controls._onMouseDown({button:2,pageX:400,pageY:300});
  controls._onMouseMove({pageX:500,pageY:350});
  controls.update();
  controls._onMouseUp();
  // No damping drain between mouseup and focus.
}
function unflushedOrbit() {
  assert.equal(controls.staticMoving,false,'left drag uses default dynamic damping');
  controls._onMouseDown({button:0,pageX:400,pageY:300});
  controls._onMouseMove({pageX:500,pageY:350});
  controls.update();
  controls._onMouseUp();
  // Select immediately after mouseup: no static mode or damping pre-drain.
}
function renderedPose() {
  return {position:camera.position.clone(),target:controls.target.clone(),
    up:camera.up.clone(),quaternion:camera.quaternion.clone()};
}
function assertRenderedStable(actual,expected,label) {
  assert.ok(actual.position.distanceTo(expected.position)<1e-9,`${label}: stable position`);
  assert.ok(actual.target.distanceTo(expected.target)<1e-9,`${label}: stable target`);
  assert.ok(actual.up.distanceTo(expected.up)<1e-10,`${label}: stable up`);
  assert.ok(actual.quaternion.toArray().every((value,index)=>
    Math.abs(value-expected.quaternion.toArray()[index])<1e-10),`${label}: stable quaternion`);
}
function assertRadialEndpoint(node,label) {
  const length=Math.hypot(node.fx,node.fy,node.fz);
  assert.ok(length>0,'radial endpoint fixture uses a non-origin node');
  const expected=new vendor.THREE.Vector3(node.fx+100*node.fx/length,
    node.fy+100*node.fy/length,node.fz+100*node.fz/length);
  assert.ok(camera.position.distanceTo(expected)<1e-9,`${label}: exact radial camera position`);
}
function assertBounds() {
  assert.equal(controls.minDistance,0.25,'manual minimum remains unchanged');
  assert.equal(controls.maxDistance,2000,'manual maximum remains unchanged');
}
function assertEndpoint(label) {
  assert.deepEqual(pose().target,{x:a.fx,y:a.fy,z:a.fz},`${label}: exact node target`);
  assert.ok(Math.abs(camera.position.distanceTo(controls.target)-100)<1e-9,
    `${label}: exact focus radius100`);
  assertBounds();
}
'''
