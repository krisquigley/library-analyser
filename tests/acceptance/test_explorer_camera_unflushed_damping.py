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
        for input_name in ('unflushedWheel', 'unflushedPan'):
            for blocked in (False, True):
                with self.subTest(input=input_name, blocked=blocked):
                    self.run_scenario(r'''
render(); manualStart(); INPUT();
// Pending input exists before blocked flags are set; settlement must drain it
// even when the user's public settings would normally suppress that input.
const config={staticMoving:BLOCKED,zoomSpeed:1.7,panSpeed:0.6,
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
