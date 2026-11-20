"""Best-effort focus with actual bundled cameraPosition and Trackball controls.

Unrepresentable custom-radius endpoints must not authorize a larger radius or
block detail after an accepted selection. No browser/WebGL claims are made.
"""
import unittest

from tests.acceptance import test_explorer_camera_custom_bounds as bounds


class CameraUnrepresentableFocusTests(unittest.TestCase):
    run_actual_vendor = bounds.CameraCustomBoundsTests.run_actual_vendor

    def test_camera_settlement_exception_cannot_suppress_accepted_detail(self):
        self.run_actual_vendor(r'''
render(); manualStart();
const initial=renderedPose();
const original=vendor.cameraPosition;
let injected=false;
vendor.cameraPosition=function(...args) {
  if(!injected) {injected=true; throw new Error('camera adapter failed');}
  return original.apply(this,args);
};
await select('a');
assert.ok(injected,'camera failure was actually exercised');
assert.deepEqual(details,['a'],'camera failure cannot suppress accepted detail GET');
assert.equal(run('getStateForTesting().current_track_id'),'a');
assertRenderedStable(renderedPose(),initial,'failed settlement restores start pose');
const writes=calls.length;
for(const time of [0,16,350,700,1200]) {
  advance(time);
  assertRenderedStable(renderedPose(),initial,`failed focus never resumes at ${time}`);
  assert.equal(calls.length,writes,'failed focus leaves no scheduled camera writes');
}
// A later accepted selection remains focusable once the adapter recovers.
vendor.cameraPosition=original;
await select('b'); advance(2000);
assert.deepEqual(details,['a','b']);
assert.deepEqual(pose().target,{x:b.fx,y:b.fy,z:b.fz});
''')


if __name__ == '__main__':
    unittest.main()
