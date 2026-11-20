"""Adjacent rendered orientations with the actual bundled Trackball controls."""
import shutil
import subprocess
import unittest

from tests.support.explorer_camera_harness import ASSETS, ROOT
from tests.support.explorer_camera_harness import FINITE_WHEEL_PAN, trackball_fixture


class CameraOrbitPathTests(unittest.TestCase):
    def run_finite_wheel_pan_scenario(self, scenario):
        # A hard timeout kills a hung vendor loop rather than leaving Node alive.
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Node required; do not skip RED')
        for asset in ASSETS:
            with self.subTest(asset=str(asset)):
                script = trackball_fixture() + FINITE_WHEEL_PAN + scenario + (
                    '\n})().then(()=>console.log("SCENARIO_COMPLETED"))'
                    '.catch(error=>{console.error(error);process.exitCode=1;});')
                result = subprocess.run(
                    ['timeout', '--signal=KILL', '20s', node, '-e', script, str(asset)],
                    cwd=ROOT, capture_output=True, text=True, timeout=25)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('SCENARIO_COMPLETED', result.stdout)

    def test_bundled_astronomical_finite_wheel_pan_rebases_target_and_restores_bounds(self):
        self.run_finite_wheel_pan_scenario(r'''
await render(); wheelAndPanToRadius(5e153);
const originalUpLength=camera.up.length();
controls.minDistance=0.25; controls.maxDistance=1e155;
const originalBounds={min:controls.minDistance,max:controls.maxDistance};
await select('a');
for(const time of [0,5,100,350,695,700,900,1200]) {
  advance(time);
  assert.deepEqual({min:controls.minDistance,max:controls.maxDistance},originalBounds,
    `temporary recovery bounds restored at ${time}`);
  assert.ok(controls.target.toArray().every(value=>Math.abs(value)<1e6),
    `exceptional target rebased to bounded location at ${time}`);
  assert.ok([...camera.position.toArray(),...controls.target.toArray(),
    ...camera.up.toArray(),...camera.quaternion.toArray()].every(Number.isFinite),
    `astronomical wheel/pan recovery preserves finite rendered pose at ${time}`);
  const offset=camera.position.clone().sub(controls.target);
  assert.ok(Number.isFinite(offset.length())&&offset.length()>1e-6,
    `bounded nonzero camera offset at ${time}`);
  assert.ok(Math.abs(camera.up.length()-originalUpLength)<1e-10,
    `normalized up preserved at ${time}`);
  assert.ok(Math.abs(camera.quaternion.length()-1)<1e-10,
    `nonzero normalized camera quaternion at ${time}`);
  if(time===700) {
    assert.deepEqual(pose().target,{x:a.fx,y:a.fy,z:a.fz},'exact target at deadline');
    assert.ok(Math.abs(offset.length()-100)<1e-9,'offset100 at deadline');
  }
}
const completed=pose(); advance(2000); assert.deepEqual(pose(),completed);
assert.equal(vendorState.tweenGroup.getAll().length,0);
''')

if __name__ == '__main__':
    unittest.main()
