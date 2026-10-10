"""Actual bundled Trackball input immediately followed by selection focus.

Unlike the large-radius orbit fixture, these inputs are deliberately not drained
or switched to staticMoving before focus. No renderer or WebGL is involved.
"""
import os
import shutil
import subprocess
import unittest

from tests.acceptance.test_explorer_camera_orbit_path import (
    FINITE_WHEEL_PAN, trackball_fixture,
)
from tests.acceptance.test_explorer_selection_camera_integration import ASSETS, ROOT


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


class CameraUnflushedDampingTests(unittest.TestCase):
    def run_scenario(self, scenario):
        node = os.environ.get('CAMERA_TEST_NODE') or shutil.which('node')
        self.assertIsNotNone(node, 'Node required; do not skip regression')
        self.assertIsNotNone(shutil.which('timeout'), 'Hard SIGKILL timeout required')
        for asset in ASSETS:
            with self.subTest(asset=str(asset.relative_to(ROOT))):
                script = trackball_fixture() + INPUTS + scenario + (
                    '\n})().then(()=>console.log("SCENARIO_COMPLETED"))'
                    '.catch(error=>{console.error(error);process.exitCode=1;});')
                # Inline script means there is no scratch file to leak on failure.
                result = subprocess.run(
                    ['timeout', '--signal=KILL', '20s', node, '-e', script, str(asset)],
                    cwd=ROOT, capture_output=True, text=True, timeout=25)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('SCENARIO_COMPLETED', result.stdout)

    def test_unflushed_left_drag_mouseup_focus_has_no_rotation_after_700ms(self):
        self.run_scenario(r'''
render(); manualStart(); unflushedOrbit();
const start=renderedPose();
await select('a');
assertRenderedStable(renderedPose(),start,'left drag selection preserves start');
advance(0);
assertRenderedStable(renderedPose(),start,'left drag elapsed zero preserves start');
for(let time=16;time<700;time+=16) {advance(time); assertBounds();}
advance(700); assertEndpoint('left drag deadline');
assertRadialEndpoint(a,'left drag deadline');
assert.ok(Math.abs(camera.up.length()-1)<1e-10,'left drag deadline has normalized transported up');
const completed=renderedPose(), observations=[];
for(let time=704;time<=1200;time+=16) {
  advance(time); assertEndpoint(`left drag ${time}`);
  assertRadialEndpoint(a,`left drag ${time}`);
  observations.push({time,pose:renderedPose()});
}
console.log('LEFT_DRAG_POST_DEADLINE',JSON.stringify(observations.map(({time,pose})=>({
  time,positionDrift:pose.position.distanceTo(completed.position),
  upDrift:pose.up.distanceTo(completed.up),
  quaternionDrift:Math.max(...pose.quaternion.toArray().map((value,index)=>
    Math.abs(value-completed.quaternion.toArray()[index])))}))));
for(const {time,pose} of observations) {
  assertRenderedStable(pose,completed,`left drag at ${time}ms after 700ms completion`);
}
''')

    def test_new_dynamic_manual_orbit_works_after_left_drag_focus_finishes(self):
        self.run_scenario(r'''
render(); manualStart(); unflushedOrbit();
await select('a'); advance(0);
for(let time=16;time<=1200;time+=16) advance(time);
assertEndpoint('before fresh manual orbit');
const focused=renderedPose();
unflushedOrbit();
const manual=renderedPose();
assert.ok(manual.position.distanceTo(focused.position)>1,'fresh left drag rotates camera');
assert.ok(manual.up.distanceTo(focused.up)>1e-3,'fresh left drag updates rendered up');
assert.equal(controls.staticMoving,false,'settlement restores dynamic movement');
assert.equal(controls.noRotate,false,'settlement does not disable later rotation');
advance(1216);
assert.ok(camera.position.distanceTo(manual.position)>1e-3,
  'fresh manual dynamic rotation still has its own inertia');
for(let time=1232;time<=2000;time+=16) {
  advance(time); assertEndpoint(`fresh manual orbit ${time}`);
  assert.ok(camera.position.distanceTo(focused.position)>1,
    'completed focus never steals the fresh manual orbit');
}
''')

    def test_unflushed_left_drag_supersession_settles_only_latest_focus(self):
        self.run_scenario(r'''
render(); manualStart(); unflushedOrbit();
await select('a'); advance(0);
for(let time=16;time<=160;time+=16) advance(time);
const moving=renderedPose();
await select('b');
assertRenderedStable(renderedPose(),moving,'supersession preserves rendered starting pose');
advance(160);
for(let time=176;time<860;time+=16) {advance(time); assertBounds();}
advance(860); assertRadialEndpoint(b,'latest focus deadline');
assert.deepEqual(pose().target,{x:b.fx,y:b.fy,z:b.fz},'latest exact target at its deadline');
assert.ok(Math.abs(camera.position.distanceTo(controls.target)-100)<1e-9,
  'latest selection radius100');
const completed=renderedPose();
for(let time=864;time<=1200;time+=16) {
  advance(time); assertBounds();
  assertRenderedStable(renderedPose(),completed,`latest left-drag focus at ${time}ms`);
}
assert.deepEqual(details,['a','b'],'selection details remain independent of focus settlement');
''')

    def test_unflushed_wheel_finishes_at_exact_target_and_radius(self):
        self.run_scenario(r'''
render(); manualStart(); unflushedWheel();
await select('a'); advance(0);
for(const time of [5,100,350,695]) {advance(time); assertBounds();}
advance(700); assertEndpoint('wheel deadline');
const completed=pose();
for(const time of [900,1200,2000]) {
  advance(time); assertEndpoint(`wheel ${time}`);
  assert.deepEqual(pose(),completed,'wheel damping cannot resume after focus');
}
''')

    def test_unflushed_pan_mouseup_then_focus_finishes_exactly(self):
        self.run_scenario(r'''
render(); manualStart(); unflushedPan();
await select('a'); advance(0);
for(const time of [5,100,350,695]) {advance(time); assertBounds();}
advance(700); assertEndpoint('pan deadline');
const completed=pose();
for(const time of [900,1200,2000]) {
  advance(time); assertEndpoint(`pan ${time}`);
  assert.deepEqual(pose(),completed,'pan damping cannot resume after focus');
}
''')

    def test_exceptional_unflushed_pan_after_mouseup_finishes_exactly(self):
        # Retain actual wheel growth and its drain, but remove ONLY the final
        # pan drain/static flush that would conceal the reported regression.
        drain = '''  for(let i=0;i<200;i++) controls.update();
  // Public static mode flushes residual pan damping without replacing controls.
  controls.staticMoving=true; controls.update(); controls.staticMoving=false;'''
        self.assertEqual(FINITE_WHEEL_PAN.count(drain), 1)
        unflushed = FINITE_WHEEL_PAN.replace(drain, '', 1)
        self.run_scenario(unflushed + r'''
render(); wheelAndPanToRadius(5e153);
controls.minDistance=0.25; controls.maxDistance=1e155;
await select('a');
for(const time of [0,100,350,695,700,900,1200,2000]) {
  advance(time);
  assert.equal(controls.minDistance,0.25,'exceptional minimum restored');
  assert.equal(controls.maxDistance,1e155,'exceptional maximum restored');
  assert.ok([...camera.position.toArray(),...controls.target.toArray(),
    ...camera.up.toArray(),...camera.quaternion.toArray()].every(Number.isFinite),
    `exceptional pending pan finite at ${time}`);
  if(time>=700) {
    assert.deepEqual(pose().target,{x:a.fx,y:a.fy,z:a.fz},
      `exceptional pending pan exact target at ${time}`);
    assert.ok(Math.abs(camera.position.distanceTo(controls.target)-100)<1e-9,
      `exceptional pending pan radius100 at ${time}`);
  }
}
const completed=pose(); advance(3000);
assert.deepEqual(pose(),completed,'exceptional pan cannot resume after completion');
''')

    def test_public_settings_and_orientation_roundtrip_and_new_inputs_work(self):
        for input_name in ('unflushedWheel', 'unflushedPan', 'unflushedOrbit'):
            for blocked in (False, True):
                with self.subTest(input=input_name, blocked=blocked):
                    self.run_scenario(r'''
render(); manualStart(); INPUT();
// Pending input exists before blocked flags are set; settlement must drain it
// even when the user's public settings would normally suppress that input.
const config={staticMoving:BLOCKED,dynamicDampingFactor:0.37,rotateSpeed:1.3,zoomSpeed:1.7,panSpeed:0.6,
  noZoom:BLOCKED,noPan:BLOCKED,noRotate:BLOCKED,minDistance:0.25,maxDistance:2000};
Object.assign(controls,config);
const settings=()=>Object.fromEntries(Object.keys(config).map(key=>[key,controls[key]]));
const initial=pose(), initialUp=camera.up.clone(), initialQuaternion=camera.quaternion.clone();
await select('a');
assert.deepEqual(settings(),config,'public settings restored immediately');
assert.deepEqual(pose(),initial,'start pose restored immediately');
assert.ok(camera.up.distanceTo(initialUp)<1e-10,'start up preserved');
assert.ok(camera.quaternion.angleTo(initialQuaternion)<1e-7,'start quaternion preserved');
advance(0);
assert.deepEqual(settings(),config,'public settings restored at elapsed zero');
assert.deepEqual(pose(),initial,'start pose preserved after vendor update');
assert.ok(camera.quaternion.angleTo(initialQuaternion)<1e-7,'start quaternion after update');
for(const time of [100,350,695,700,900,1200]) {
  advance(time); assert.deepEqual(settings(),config,`public settings restored at ${time}`);
  if(time>=700) assertEndpoint(`settings endpoint ${time}`);
}
// Explicitly re-enable blocked inputs only AFTER checking restoration. Actual
// vendor wheel and pan must still work with the preserved configured speeds.
Object.assign(controls,{noZoom:false,noPan:false,noRotate:false});
const focused=pose();
unflushedWheel();
assert.notDeepEqual(pose().position,focused.position,'new actual wheel still moves camera');
const wheeled=pose(); unflushedPan();
assert.notDeepEqual(pose().target,wheeled.target,'new actual right-button pan still moves target');
assertBounds();
'''.replace('INPUT()', input_name + '()').replace('BLOCKED', str(blocked).lower()))

    def test_ordinary_start_pose_and_radius_are_preserved(self):
        for input_name in ('unflushedWheel', 'unflushedPan'):
            with self.subTest(input=input_name):
                self.run_scenario(r'''
render(); manualStart(); INPUT();
const start=pose(), radius=camera.position.distanceTo(controls.target);
await select('a');
assert.deepEqual(pose(),start,'ordinary start is not rebased on selection');
advance(0);
assert.deepEqual(pose(),start,'ordinary start pose preserved at elapsed zero');
assert.ok(Math.abs(camera.position.distanceTo(controls.target)-radius)<1e-9,
  'ordinary starting radius preserved');
assertBounds();
'''.replace('INPUT()', input_name + '()'))

    def test_manual_orbit_cancels_unflushed_input_focus_and_retains_bounds(self):
        for input_name in ('unflushedWheel', 'unflushedPan'):
            with self.subTest(input=input_name):
                self.run_scenario(r'''
render(); manualStart(); INPUT();
await select('a'); advance(0); advance(100);
// Static manual interaction avoids confusing legitimate new orbit inertia with
// a stale focus write; the unflushed pre-focus inputs above remain dynamic.
const staticMoving=controls.staticMoving;
controls.staticMoving=true;
controls._onMouseDown({button:0,pageX:400,pageY:300});
controls._onMouseMove({pageX:420,pageY:310});
controls.update(); controls._onMouseUp();
controls.update();
const manual=pose(), manualUp=camera.up.clone();
for(const time of [200,700,900,1200,2000]) {
  advance(time); assertBounds();
  assert.deepEqual(pose(),manual,'cancelled focus cannot overwrite manual orbit');
  assert.ok(camera.up.distanceTo(manualUp)<1e-10,'manual up retained');
}
controls.staticMoving=staticMoving;
'''.replace('INPUT()', input_name + '()'))


if __name__ == '__main__':
    unittest.main()
