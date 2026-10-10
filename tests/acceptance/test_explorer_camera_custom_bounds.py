"""Custom focus radii with actual bundled cameraPosition and Trackball controls.

Observe both the application's requested camera position and the rendered pose:
checking only after Trackball.update would conceal an out-of-bounds focus path.
No WebGL, browser or wall-clock animation is involved.
"""
import os
import shutil
import subprocess
import unittest

from tests.acceptance.test_explorer_camera_orbit_path import FINITE_WHEEL_PAN, trackball_fixture
from tests.acceptance.test_explorer_camera_unflushed_damping import INPUTS
from tests.acceptance.test_explorer_selection_camera_integration import ASSETS, ROOT


BOUNDED_FOCUS = r'''
const selected=ORIGIN?node('origin',0,0,0):a;
render(model([selected,b])); manualStart();
const config={enabled:true,staticMoving:false,dynamicDampingFactor:0.37,
  rotateSpeed:1.3,zoomSpeed:1.7,panSpeed:0.6,noZoom:false,noPan:false,noRotate:false,
  minDistance:MINIMUM,maxDistance:MAXIMUM};
Object.assign(controls,config);
const startRadius=START_RADIUS;
camera.position.copy(controls.target).add(new vendor.THREE.Vector3(1,-0.4,0.3)
  .normalize().multiplyScalar(startRadius));
controls.update(); INPUT();
const settings=()=>Object.fromEntries(Object.keys(config).map(key=>[key,controls[key]]));
const initial=renderedPose(), initialRadius=camera.position.distanceTo(controls.target);
assert.ok(initialRadius>=config.minDistance&&initialRadius<=config.maxDistance,
  'manual starting pose is already within custom bounds');
await select(selected.id);
assertRenderedStable(renderedPose(),initial,'selection preserves bounded manual start');
assert.deepEqual(settings(),config,'settlement restores all public settings immediately');
advance(0);
assertRenderedStable(renderedPose(),initial,'elapsed zero preserves bounded start');
const expectedRadius=Math.max(config.minDistance,Math.min(config.maxDistance,100));
const direction=ORIGIN?initial.position.clone().sub(initial.target).normalize():
  new vendor.THREE.Vector3(selected.fx,selected.fy,selected.fz).normalize();
const endpoint=new vendor.THREE.Vector3(selected.fx,selected.fy,selected.fz)
  .add(direction.multiplyScalar(expectedRadius));
for(const time of [16,100,350,600,695,700,704,900,1200]) {
  advance(time);
  assert.deepEqual(settings(),config,`public settings retained at ${time}`);
  const request=calls.at(-1), requestedPosition=new vendor.THREE.Vector3(
    request.position.x,request.position.y,request.position.z);
  const requestedTarget=new vendor.THREE.Vector3(request.target.x,request.target.y,request.target.z);
  const requestedRadius=requestedPosition.distanceTo(requestedTarget);
  assert.ok(requestedRadius>=config.minDistance-1e-9&&requestedRadius<=config.maxDistance+1e-9,
    `focus setter radius ${requestedRadius} respects custom bounds before Trackball update at ${time}`);
  assert.ok(camera.position.distanceTo(requestedPosition)<1e-9,
    `vendor bounds must not snap the focus camera after its setter at ${time}`);
  assert.ok([...camera.position.toArray(),...controls.target.toArray(),
    ...camera.up.toArray(),...camera.quaternion.toArray()].every(Number.isFinite),
    `finite bounded rendered pose at ${time}`);
  assert.ok(Math.abs(camera.quaternion.length()-1)<1e-10,`normalized quaternion at ${time}`);
  if(time===100) {
    assert.ok(controls.target.distanceTo(initial.target)>1,'focus target moves smoothly');
    assert.ok(camera.position.distanceTo(endpoint)>1,'focus does not jump to endpoint');
  }
  if(time>=700) {
    assert.deepEqual(pose().target,{x:selected.fx,y:selected.fy,z:selected.fz},
      `exact node target at ${time}`);
    assert.ok(camera.position.distanceTo(endpoint)<1e-9,
      `custom radius takes precedence over nominal100 at ${time}`);
  }
}
const completed=renderedPose();
for(const time of [1400,2000,3000]) {
  advance(time); assertRenderedStable(renderedPose(),completed,`bounded completion stable at ${time}`);
  assert.deepEqual(settings(),config,`custom settings unchanged after completion at ${time}`);
}
assert.equal(vendorState.tweenGroup.getAll().length,0,'no private vendor tween bypass');
'''


class CameraCustomBoundsTests(unittest.TestCase):
    def run_actual_vendor(self, scenario, inputs=INPUTS):
        node = os.environ.get('CAMERA_TEST_NODE') or shutil.which('node')
        self.assertIsNotNone(node, 'Node required; do not skip RED')
        self.assertIsNotNone(shutil.which('timeout'), 'Hard SIGKILL timeout required')
        for asset in ASSETS:
            with self.subTest(asset=str(asset.relative_to(ROOT))):
                script = trackball_fixture() + inputs + scenario + (
                    '\n})().then(()=>console.log("SCENARIO_COMPLETED"))'
                    '.catch(error=>{console.error(error);process.exitCode=1;});')
                result = subprocess.run(
                    ['timeout', '--signal=KILL', '20s', node, '-e', script, str(asset)],
                    cwd=ROOT, capture_output=True, text=True, timeout=25)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('SCENARIO_COMPLETED', result.stdout)

    def run_scenario(self, minimum, maximum, start_radius, input_name, origin=False):
        scenario = (BOUNDED_FOCUS.replace('MINIMUM', str(minimum))
                    .replace('MAXIMUM', str(maximum)).replace('START_RADIUS', str(start_radius))
                    .replace('INPUT()', input_name + '()').replace('ORIGIN', str(origin).lower()))
        with self.subTest(input=input_name, origin=origin):
            self.run_actual_vendor(scenario)

    def test_astronomical_recovery_uses_custom_minimum_without_vendor_snap(self):
        self.run_actual_vendor(r'''
render(); wheelAndPanToRadius(5e153);
controls.minDistance=250; controls.maxDistance=1e155;
await select('a');
for(const time of [0,16,100,350,695,700,900,1200]) {
  advance(time);
  assert.equal(controls.minDistance,250,'recovery restores custom minimum');
  assert.equal(controls.maxDistance,1e155,'recovery restores custom maximum');
  const request=calls.at(-1), requestedPosition=new vendor.THREE.Vector3(
    request.position.x,request.position.y,request.position.z);
  const requestedTarget=new vendor.THREE.Vector3(request.target.x,request.target.y,request.target.z);
  assert.ok(requestedPosition.distanceTo(requestedTarget)>=250-1e-9,
    `exceptional recovery respects custom minimum before vendor update at ${time}`);
  assert.ok(camera.position.distanceTo(requestedPosition)<1e-9,
    `exceptional recovery needs no vendor radius snap at ${time}`);
  assert.ok([...camera.position.toArray(),...controls.target.toArray(),
    ...camera.up.toArray(),...camera.quaternion.toArray()].every(Number.isFinite),
    `custom bounded recovery rendered pose remains finite at ${time}`);
  if(time>=700) {
    assert.deepEqual(pose().target,{x:a.fx,y:a.fy,z:a.fz},'recovery exact node target');
    assert.ok(Math.abs(camera.position.distanceTo(controls.target)-250)<1e-9,
      'custom minimum takes precedence over nominal100 in recovery');
  }
}
const completed=pose(); advance(2000); assert.deepEqual(pose(),completed);
''', inputs=FINITE_WHEEL_PAN)

    def test_minimum_above_nominal_radius_bounds_the_entire_focus_path(self):
        for input_name in ('unflushedWheel', 'unflushedPan', 'unflushedOrbit'):
            self.run_scenario(250, 600, 400, input_name)

    def test_maximum_below_nominal_radius_bounds_the_entire_focus_path(self):
        for input_name in ('unflushedWheel', 'unflushedPan', 'unflushedOrbit'):
            self.run_scenario(10, 60, 40, input_name)

    def test_positioned_origin_preserves_direction_with_minimum_above_nominal(self):
        self.run_scenario(250, 600, 400, 'unflushedPan', origin=True)

    def test_positioned_origin_preserves_direction_with_maximum_below_nominal(self):
        self.run_scenario(10, 60, 40, 'unflushedPan', origin=True)


if __name__ == '__main__':
    unittest.main()
