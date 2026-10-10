"""Disabled selection focus using the actual bundled setter and Trackball.

The vendor's disabled setter looks at the supplied point without updating the
public orbit target. The adapter must keep that target synchronized so both
render-loop updates and subsequent re-enabling retain the rendered orientation.
"""
import unittest

from tests.acceptance import test_explorer_camera_unflushed_damping as damping


class CameraDisabledControlsTests(unittest.TestCase):
    # Reuse the hard-SIGKILL actual-vendor runner, including its input helpers.
    run_scenario = damping.CameraUnflushedDampingTests.run_scenario
    def test_disabled_initial_and_replacement_frames_sync_orbit_target(self):
        for replacement in (False, True):
            with self.subTest(replacement=replacement):
                self.run_scenario(r'''
if(REPLACEMENT) {render(); manualStart();}
const config={enabled:false,staticMoving:false,dynamicDampingFactor:0.37,
  rotateSpeed:1.3,zoomSpeed:1.7,panSpeed:0.6,noZoom:true,noPan:true,noRotate:true,
  minDistance:0.25,maxDistance:2000};
Object.assign(controls,config);
const settings=()=>Object.fromEntries(Object.keys(config).map(key=>[key,controls[key]]));
const stale=controls.target.clone();
render(model([node('a',0.8,0.4,0.6),node('b',0.2,0.9,0.7)]));
const framed=renderedPose(), requested=calls.at(-1).target;
assert.ok(new vendor.THREE.Vector3(requested.x,requested.y,requested.z).distanceTo(stale)>1,
  'off-origin layout exposes stale disabled orbit target');
assert.deepEqual(pose().target,requested,'disabled framing synchronizes public orbit target');
assert.deepEqual(settings(),config,'framing preserves all public settings');
controls.update();
assertRenderedStable(renderedPose(),framed,'disabled frame survives vendor update');
controls.enabled=true; controls.update();
assertRenderedStable(renderedPose(),framed,'disabled frame survives reenable');
'''.replace('REPLACEMENT', 'true' if replacement else 'false'))

    def test_first_focus_after_disabled_frame_preserves_starting_quaternion(self):
        for replacement in (False, True):
            with self.subTest(replacement=replacement):
                self.run_scenario(r'''
if(REPLACEMENT) {render(); manualStart();}
const config={enabled:false,staticMoving:false,dynamicDampingFactor:0.37,
  rotateSpeed:1.3,zoomSpeed:1.7,panSpeed:0.6,noZoom:true,noPan:true,noRotate:true,
  minDistance:0.25,maxDistance:2000};
Object.assign(controls,config);
const settings=()=>Object.fromEntries(Object.keys(config).map(key=>[key,controls[key]]));
render(model([node('a',0.8,0.4,0.6),node('b',0.2,0.9,0.7)]));
const framed=renderedPose();
await select('a');
assertRenderedStable(renderedPose(),framed,'selection preserves disabled framed pose');
advance(0);
assertRenderedStable(renderedPose(),framed,'first focus elapsed zero preserves framed quaternion');
advance(700);
const completed=renderedPose();
advance(1200);
assertRenderedStable(renderedPose(),completed,'first focus completes without resumed motion');
assert.deepEqual(settings(),config,'focus preserves all public settings');
'''.replace('REPLACEMENT', 'true' if replacement else 'false'))

    def test_disabled_held_reload_frames_before_latest_accepted_focus(self):
        self.run_scenario(r'''
render(); manualStart();
const config={enabled:false,staticMoving:false,dynamicDampingFactor:0.37,
  rotateSpeed:1.3,zoomSpeed:1.7,panSpeed:0.6,noZoom:true,noPan:true,noRotate:true,
  minDistance:0.25,maxDistance:2000};
Object.assign(controls,config);
const settings=()=>Object.fromEntries(Object.keys(config).map(key=>[key,controls[key]]));
const old=renderedPose(); calls.length=0;
let resolveGraph;
graphHook=()=>new Promise(resolve=>{resolveGraph=resolve;});
const reload=run('loadGraph()');
assert.equal(run('graphLoadState.status'),'loading');
await select('a'); await select('b');
assert.deepEqual(details,['a','b'],'details remain usable during held replacement');
assert.equal(calls.length,0,'accepted B cannot focus on old layout');
assertRenderedStable(renderedPose(),old,'held replacement preserves old rendered pose');
resolveGraph({ok:true,json:async()=>({dto_version:'mood-axis-graph-indexed-v1',
  selected_mood:'',available_moods:[],
  axis:[{key:'x',label:'Valence',scale:'unit'},{key:'y',label:'Arousal',scale:'unit'},
        {key:'z',label:'BPM',scale:'bpm'}],
  nodes:[['a','A',0.1,0.1,0.2,0.2,120,0.4,null,0.6,[[0,0.8]],[]],
         ['b','B',0.9,0.9,-0.3,-0.3,120,0.4,null,0.6,[[0,0.8]],[]]],
  links:[],unpositioned:[],genre_labels:['ambient'],reason_text:[],
  explanation_table:[],provenance_table:[],metadata:{graph_status:{state:'ready'}}})});
for(let i=0;i<20;i++) await Promise.resolve();
assert.equal(run('graphLoadState.status'),'rendering');
tick(); await reload;
assert.equal(calls[0].duration,0,'replacement starts with immediate layout framing');
assert.deepEqual(calls.at(-1).target,calls[0].target,'focus begins at replacement framed target');
assert.deepEqual(pose().target,calls[0].target,'replacement synchronizes disabled orbit target');
const framed=renderedPose();
advance(0);
assertRenderedStable(renderedPose(),framed,'replacement first focus elapsed zero quaternion');
assert.deepEqual(settings(),config,'replacement and focus preserve all public settings');
advance(700);
const expected=liveData.nodes.find(node=>node.id==='b');
assert.deepEqual(pose().target,{x:expected.fx,y:expected.fy,z:expected.fz},
  'latest B focuses replacement coordinates at deadline');
const completed=renderedPose(); advance(1200);
assertRenderedStable(renderedPose(),completed,'replacement focus remains stable');
assert.deepEqual(settings(),config,'completed replacement focus preserves all public settings');
''')

    def test_actual_vendor_disabled_setter_leaves_orbit_target_stale(self):
        self.run_scenario(r'''
render(); manualStart();
controls.enabled=false;
const oldTarget=controls.target.clone();
const position={x:501,y:402,z:303}, target={x:51,y:42,z:33};
vendor.cameraPosition(vendorState,position,target,0);
assert.ok(controls.target.distanceTo(oldTarget)<1e-9,
  'bundled disabled camera setter leaves public target stale');
const expected=camera.clone(); expected.lookAt(new vendor.THREE.Vector3(target.x,target.y,target.z));
assert.ok(camera.quaternion.angleTo(expected.quaternion)<1e-7,
  'bundled disabled setter renders the requested look-at');
const rendered=camera.quaternion.clone();
controls.update();
assert.ok(camera.quaternion.angleTo(rendered)>0.01,
  'actual Trackball update redirects orientation to stale orbit target');
''')

    def test_disabled_focus_syncs_target_and_survives_reenable_with_pending_input(self):
        for input_name in ('none', 'unflushedWheel', 'unflushedPan', 'unflushedOrbit'):
            with self.subTest(input=input_name):
                self.run_scenario(r'''
render(); manualStart(); INPUT();
const config={enabled:false,staticMoving:false,dynamicDampingFactor:0.37,
  rotateSpeed:1.3,zoomSpeed:1.7,panSpeed:0.6,noZoom:true,noPan:true,noRotate:true,
  minDistance:0.25,maxDistance:2000};
Object.assign(controls,config);
const settings=()=>Object.fromEntries(Object.keys(config).map(key=>[key,controls[key]]));
const initial=renderedPose();
await select('a');
assert.deepEqual(settings(),config,'selection restores all public settings including disabled');
assertRenderedStable(renderedPose(),initial,'disabled selection preserves starting rendered pose');
advance(0);
assertRenderedStable(renderedPose(),initial,'elapsed zero preserves disabled rendered pose');
for(const time of [100,350,695,700,900,1200]) {
  advance(time);
  assert.deepEqual(settings(),config,`disabled settings unchanged at ${time}`);
  const requestedTarget=calls.at(-1).target;
  assert.deepEqual(pose().target,requestedTarget,
    `disabled public orbit target matches requested look-at at ${time}`);
  // Independently compare the post-update orientation to the requested target.
  const expected=camera.clone();
  expected.lookAt(new vendor.THREE.Vector3(requestedTarget.x,requestedTarget.y,requestedTarget.z));
  assert.ok(camera.quaternion.angleTo(expected.quaternion)<1e-7,
    `rendered quaternion agrees with synchronized orbit target at ${time}`);
  if(time>=700) {assertEndpoint(`disabled endpoint ${time}`); assertRadialEndpoint(a,`disabled endpoint ${time}`);}
}
const completed=renderedPose();
Object.assign(controls,{enabled:true,noZoom:false,noPan:false,noRotate:false});
for(const time of [1216,1232,1300,2000]) {
  advance(time);
  assertRenderedStable(renderedPose(),completed,`reenabled pose at ${time}`);
}
// Re-enabled controls retain configured dynamics and support fresh manual input.
const focused=renderedPose(); unflushedOrbit();
assert.ok(camera.position.distanceTo(focused.position)>1,'fresh re-enabled orbit moves camera');
const manual=renderedPose(); advance(2016);
assert.ok(camera.position.distanceTo(manual.position)>1e-3,
  'fresh dynamic damping remains enabled after disabled focus');
'''.replace('INPUT()', '' if input_name == 'none' else input_name + '()'))


if __name__ == '__main__':
    unittest.main()
