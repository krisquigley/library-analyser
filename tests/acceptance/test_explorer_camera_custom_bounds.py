"""Custom focus radii with actual bundled cameraPosition and Trackball controls.

Observe both the application's requested camera position and the rendered pose:
checking only after Trackball.update would conceal an out-of-bounds focus path.
No WebGL, browser or wall-clock animation is involved.
"""
import os
import shutil
import subprocess
import unittest

from tests.support.explorer_camera_harness import FINITE_WHEEL_PAN, trackball_fixture
from tests.support.explorer_camera_harness import INPUTS
from tests.support.explorer_camera_harness import ASSETS, ROOT


class CameraCustomBoundsTests(unittest.TestCase):
    def run_actual_vendor(self, scenario, inputs=INPUTS):
        node = os.environ.get('CAMERA_TEST_NODE') or shutil.which('node')
        self.assertIsNotNone(node, 'Node required; do not skip RED')
        self.assertIsNotNone(shutil.which('timeout'), 'Hard SIGKILL timeout required')
        for asset in ASSETS:
            with self.subTest(asset=str(asset)):
                script = trackball_fixture() + inputs + scenario + (
                    '\n})().then(()=>console.log("SCENARIO_COMPLETED"))'
                    '.catch(error=>{console.error(error);process.exitCode=1;});')
                result = subprocess.run(
                    ['timeout', '--signal=KILL', '20s', node, '-e', script, str(asset)],
                    cwd=ROOT, capture_output=True, text=True, timeout=25)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('SCENARIO_COMPLETED', result.stdout)

    def test_astronomical_recovery_uses_custom_minimum_without_vendor_snap(self):
        self.run_actual_vendor(r'''
await render(); wheelAndPanToRadius(5e153);
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

if __name__ == '__main__':
    unittest.main()
