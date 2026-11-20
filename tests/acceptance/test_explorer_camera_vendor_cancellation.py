"""Time-stepped camera tests using bundled THREE, TWEEN and cameraPosition.

The bundle is evaluated with a test-only export at its closure boundary. Its
camera method and tween implementation are neither rewritten nor mocked. No
renderer, WebGL, database or wall-clock animation is involved.
"""
import shutil
import subprocess
import unittest

from tests.support.explorer_camera_harness import ASSETS, ROOT
from tests.support.explorer_camera_harness import real_vendor_fixture


class CameraVendorCancellationTests(unittest.TestCase):
    def run_scenario(self, scenario):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Node required; do not skip RED')
        for asset in ASSETS:
            with self.subTest(asset=str(asset)):
                script = real_vendor_fixture() + scenario + (
                    '\n})().then(()=>console.log("SCENARIO_COMPLETED"))'
                    '.catch(error=>{console.error(error);process.exitCode=1;});')
                result = subprocess.run([node, '-e', script, str(asset)], cwd=ROOT,
                                        capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('SCENARIO_COMPLETED', result.stdout)

    def test_missing_selection_cancels_motion_without_later_vendor_overwrite(self):
        self.run_scenario(r'''
await render(); await select('a'); advance(0); advance(100);
const moving=pose();
await select('missing');
const stopped=pose();
assert.deepEqual(stopped,moving,'cancellation preserves current pose');
advance(200); advance(800); advance(1200);
assert.deepEqual(pose(),stopped,'no superseded camera or target tween writes later');
assert.equal(vendorState.tweenGroup.getAll().length,0,'application focus leaves no private vendor tweens');
assert.deepEqual(details,['a','missing'],'detail remains independent');
''')

    def test_unpositioned_selection_cancels_both_camera_and_target(self):
        self.run_scenario(r'''
const data=model(); data.unpositioned=[{track_id:'unpositioned'}];
await render(data); await select('a'); advance(0); advance(100);
const stopped=pose();
await select('unpositioned'); advance(200); advance(800); advance(1200);
assert.deepEqual(pose(),stopped,'unpositioned selection cancels both real vendor write paths');
assert.deepEqual(details,['a','unpositioned']);
assert.equal(vendorState.tweenGroup.getAll().length,0);
''')

    def test_user_orbit_start_cancels_motion_and_preserves_manual_pose(self):
        self.run_scenario(r'''
await render(); await select('a'); advance(0); advance(100);
controls.dispatchEvent({type:'start'});
camera.position.set(901,802,703); controls.target.set(91,82,73);
const manual=pose();
advance(200); advance(800); advance(1200);
assert.deepEqual(pose(),manual,'user orbit cannot be overwritten after old focus deadline');
assert.equal(vendorState.tweenGroup.getAll().length,0);
''')

    def test_reset_cancels_motion_and_preserves_manual_pose_past_old_deadline(self):
        self.run_scenario(r'''
await render(); await select('a'); advance(0); advance(100);
historyHook=()=>({current_track_id:null,history:[],selection_epoch:1});
await history('/api/reset');
camera.position.set(901,802,703); controls.target.set(91,82,73);
const manual=pose();
advance(200); advance(800); advance(1200);
assert.deepEqual(pose(),manual,'reset cannot leave private vendor tweens stealing manual orbit');
assert.equal(vendorState.tweenGroup.getAll().length,0);
''')

    def test_new_selection_is_smooth_and_finishes_only_at_latest_target(self):
        self.run_scenario(r'''
await render(); await select('a'); advance(0); const initial=pose(); advance(100);
assert.notDeepEqual(pose().position,initial.position,'focus moves over time');
await select('b'); advance(100); advance(200);
assert.notDeepEqual(pose().target,{x:b.fx,y:b.fy,z:b.fz},'latest focus is not an immediate jump');
advance(800); advance(1200);
assert.deepEqual(pose().target,{x:b.fx,y:b.fy,z:b.fz});
const completed=pose(); advance(2000);
assert.deepEqual(pose(),completed,'no superseded writes after completion');
assert.equal(vendorState.tweenGroup.getAll().length,0,'bounded application animation never accumulates private tweens');
''')


if __name__ == '__main__':
    unittest.main()
