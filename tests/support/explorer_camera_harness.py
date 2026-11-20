"""The camera tests' shared Node harness for the Explorer app: fixture, vendored graph library and recorded inputs (#146)."""
from pathlib import Path
from tests.support.explorer_app_bundle import explorer_app_script


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
    calls.push({position:{...position},target:{...target},duration,at:fixtureClock});
    Object.assign(camera.position,position); Object.assign(controls.target,target);
    return graph;
  };
  if(key==='onNodeClick') return fn=>{clickHandler=fn; return graph;};
  return ()=>graph;
}});
const resizeCallbacks=[];
class ResizeObserver {constructor(callback){resizeCallbacks.push(callback);} observe(){} }
let graphHook=null;
let postHook=null, historyHook=null, authoritativeSnapshot={current_track_id:null,history:[],selection_epoch:0};
let clickHandler=null;
const context=vm.createContext({console,URLSearchParams,setTimeout,clearTimeout,
  requestAnimationFrame:fn=>{frames.push(fn);return frames.length;},performance:{now:()=>fixtureClock},ResizeObserver,
  ForceGraph3D:()=>()=>graph,
  fetch:async(path,options)=>{
    requests.push({path,options});
    if(path.startsWith('/api/mood-axis-graph') && graphHook) return graphHook();
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
function tick() {fixtureClock+=700; const pending=frames.splice(0); for(const callback of pending) callback(fixtureClock);}
async function history(path) {
  const promise=run(`applyHistorySelection(${JSON.stringify(path.replace("/api/",""))})`);
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
