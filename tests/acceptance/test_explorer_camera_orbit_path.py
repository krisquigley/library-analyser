"""Adjacent rendered orientations with the actual bundled Trackball controls."""
import shutil
import subprocess
import unittest

from tests.acceptance.test_explorer_camera_vendor_cancellation import real_vendor_fixture
from tests.acceptance.test_explorer_selection_camera_integration import ASSETS, ROOT


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


class CameraOrbitPathTests(unittest.TestCase):
    def test_finite_subnormal_camera_gap_keeps_rendered_pose_finite(self):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Node required; do not skip RED')
        scenario = r'''
render();
// A finite boundary pose reached by extreme zoom, without an unbounded wheel loop.
controls.target.set(0,0,0);
camera.position.set(0,0,1.7e-309);
camera.up.set(0,1,0);
controls.update();
assert.equal(camera.position.z,1.7e-309,'actual Trackball retains the finite tiny gap');
assert.ok(!Number.isFinite(1/Math.hypot(camera.position.x,camera.position.y,camera.position.z)),
  'fixture exercises reciprocal overflow');
const assertFinite=()=>assert.ok([...camera.position.toArray(),...camera.up.toArray(),
  ...camera.quaternion.toArray(),...controls.target.toArray()].every(Number.isFinite),
  'finite camera position, up and quaternion throughout and after focus');
assertFinite();
await select('a');
for(const time of [0,5,100,350,695,700,900,1200]) {advance(time); assertFinite();}
assert.deepEqual(pose().target,{x:a.fx,y:a.fy,z:a.fz});
assert.ok(Math.abs(camera.position.distanceTo(controls.target)-100)<1e-9,
  'tiny start gap still reaches useful radial framing');
assert.equal(vendorState.tweenGroup.getAll().length,0,'no private vendor tweens');
'''
        for asset in ASSETS:
            with self.subTest(asset=str(asset.relative_to(ROOT))):
                script = trackball_fixture() + scenario + (
                    '\n})().then(()=>console.log("SCENARIO_COMPLETED"))'
                    '.catch(error=>{console.error(error);process.exitCode=1;});')
                # subprocess.run kills (SIGKILL) and reaps Node on TimeoutExpired.
                result = subprocess.run([node, '-e', script, str(asset)], cwd=ROOT,
                                        capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('SCENARIO_COMPLETED', result.stdout)

    def test_focus_preserves_manual_orbit_without_adjacent_frame_flip(self):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Node required; do not skip RED')
        scenario = r'''
render();
// A legitimate manual orbit opposite the selected node's radial direction.
// The original linear path passes exactly through its look-at target.
controls.target.set(0,0,0);
camera.position.set(-a.fx,-a.fy,-a.fz);
camera.up.set(0.2,1,0.3).normalize();
controls.update();
const initialOffset=camera.position.clone().sub(controls.target).normalize();
const initialUp=camera.up.clone();
const initialPose=pose();
await select('a');
let previous=camera.quaternion.clone();
const times=[...new Set([...Array.from({length:141},(_,i)=>i*5),348,352])].filter(time=>time!==350).sort((a,b)=>a-b);
for(const time of times) {
  advance(time);
  const offset=camera.position.clone().sub(controls.target);
  assert.ok([...camera.position.toArray(),...controls.target.toArray(),
    ...camera.quaternion.toArray()].every(Number.isFinite),'finite rendered pose');
  assert.ok(offset.length()>1e-6,'nondegenerate look-at distance at every frame');
  const angle=previous.angleTo(camera.quaternion);
  assert.ok(angle<0.05,`adjacent rendered orientation must not flip: ${angle} at ${time}`);
  if(time===0) assert.ok(offset.normalize().dot(initialOffset)>1-1e-10,
    'focus begins at legitimate manual orbit direction');
  previous=camera.quaternion.clone();
  if(time===100) {
    assert.notDeepEqual(pose(),initialPose,'positive elapsed time moves camera smoothly');
    const radialLength=Math.hypot(a.fx,a.fy,a.fz);
    assert.notDeepEqual(pose().position,{x:a.fx+100*a.fx/radialLength,
      y:a.fy+100*a.fy/radialLength,z:a.fz+100*a.fz/radialLength},'not an immediate snap');
  }
}
assert.deepEqual(pose().target,{x:a.fx,y:a.fy,z:a.fz});
assert.ok(Math.abs(camera.position.distanceTo(controls.target)-100)<1e-9,'useful final framing');
const radial=new vendor.THREE.Vector3(a.fx,a.fy,a.fz).normalize();
assert.ok(camera.position.clone().sub(controls.target).normalize().dot(radial)>1-1e-10,
  'original radial endpoint remains exact');
assert.ok(Math.abs(camera.up.length()-initialUp.length())<1e-10,'transport keeps up normalized');
const completed=pose(); advance(900); assert.deepEqual(pose(),completed);
// A new focus starts from this orbit, and user interaction cancels both writes.
await select('b'); advance(1000);
controls.dispatchEvent({type:'start'});
camera.position.set(901,802,703); controls.target.set(91,82,73); controls.update();
const manual=pose(), manualUp=camera.up.clone(), manualOrientation=camera.quaternion.clone();
advance(1100); advance(2000);
assert.deepEqual(pose(),manual,'no focus write after manual orbit cancellation');
assert.ok(camera.up.distanceTo(manualUp)<1e-10,'cancelled arc cannot overwrite manual up');
assert.ok(camera.quaternion.angleTo(manualOrientation)<1e-7,'manual orientation stays unchanged');
assert.equal(vendorState.tweenGroup.getAll().length,0,'no private vendor tweens');
'''
        cases = {
            'review_exact_pose': 'Object.assign(a,node("a",0,0,1));\n' + scenario.replace(
                'controls.target.set(0,0,0);\ncamera.position.set(-a.fx,-a.fy,-a.fz);\n'
                'camera.up.set(0.2,1,0.3).normalize();',
                'controls.target.set(0,0,200);\ncamera.position.set(0,0,100);\n'
                'camera.up.set(0,1,0);'),
            'antiparallel': scenario,
            'world_up_endpoint': 'Object.assign(a,node("a",0,1,0));\n' + scenario,
            'oblique': scenario.replace('camera.position.set(-a.fx,-a.fy,-a.fz);',
                                        'camera.position.set(70,-160,-30);'),
        }
        for asset in ASSETS:
            for name, case in cases.items():
                with self.subTest(asset=str(asset.relative_to(ROOT)), path=name):
                    script = trackball_fixture() + case + (
                        '\n})().then(()=>console.log("SCENARIO_COMPLETED"))'
                        '.catch(error=>{console.error(error);process.exitCode=1;});')
                    result = subprocess.run([node, '-e', script, str(asset)], cwd=ROOT,
                                            capture_output=True, text=True, timeout=20)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn('SCENARIO_COMPLETED', result.stdout)


if __name__ == '__main__':
    unittest.main()
