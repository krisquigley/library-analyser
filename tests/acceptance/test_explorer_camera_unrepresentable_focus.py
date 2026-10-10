"""Best-effort focus with actual bundled cameraPosition and Trackball controls.

Unrepresentable custom-radius endpoints must not authorize a larger radius or
block detail after an accepted selection. No browser/WebGL claims are made.
"""
import unittest

from tests.acceptance import test_explorer_camera_custom_bounds as bounds


class CameraUnrepresentableFocusTests(unittest.TestCase):
    run_actual_vendor = bounds.CameraCustomBoundsTests.run_actual_vendor

    def test_unrepresentable_endpoint_skips_focus_without_changing_custom_bounds(self):
        for maximum in (0, 5e-324, 1e-15):
            with self.subTest(maximum=maximum):
                self.run_actual_vendor(r'''
render();
Object.assign(controls,{minDistance:0,maxDistance:MAXIMUM});
controls.target.set(0,0,0); camera.position.set(0,0,MAXIMUM);
controls.update();
const initial=renderedPose(), bounds={min:controls.minDistance,max:controls.maxDistance};
const callsBefore=calls.length;
await select('a');
assert.deepEqual(details,['a'],'accepted selection still requests independent detail');
assert.equal(run('getStateForTesting().current_track_id'),'a','accepted selection remains current');
assert.equal(calls.length,callsBefore,'unrepresentable focus does not attempt camera writes');
assertRenderedStable(renderedPose(),initial,'ineligible focus leaves rendered start intact');
for(const time of [0,16,350,700,1200]) {
  advance(time);
  assertRenderedStable(renderedPose(),initial,`skipped focus stable at ${time}`);
  assert.deepEqual({min:controls.minDistance,max:controls.maxDistance},bounds,
    `custom zero/tiny maximum never widened at ${time}`);
  assert.equal(calls.length,callsBefore,`no delayed focus writes at ${time}`);
  assert.ok([...camera.position.toArray(),...controls.target.toArray(),
    ...camera.up.toArray(),...camera.quaternion.toArray()].every(Number.isFinite),
    `skipped focus pose remains finite at ${time}`);
}
assert.equal(vendorState.tweenGroup.getAll().length,0);
'''.replace('MAXIMUM', str(maximum)))

    def test_tiny_but_representable_endpoint_still_focuses(self):
        self.run_actual_vendor(r'''
render();
Object.assign(controls,{minDistance:0,maxDistance:1e-12});
controls.target.set(0,0,0); camera.position.set(0,0,1e-12);
controls.update();
const callsBefore=calls.length;
await select('a');
assert.deepEqual(details,['a'],'representable tiny endpoint keeps detail independent');
advance(700);
assert.ok(calls.length>callsBefore,'representable tiny radius must not skip focus');
assert.deepEqual(pose().target,{x:a.fx,y:a.fy,z:a.fz},'exact selected node target');
const radius=camera.position.distanceTo(controls.target);
assert.ok(radius>0,'tiny endpoint retains a representable nonzero view direction');
assert.ok(Math.abs(radius-1e-12)<2e-14,
  'endpoint stays at custom tiny radius within coordinate rounding precision');
assert.equal(controls.minDistance,0); assert.equal(controls.maxDistance,1e-12);
assert.ok([...camera.position.toArray(),...controls.target.toArray(),
  ...camera.up.toArray(),...camera.quaternion.toArray()].every(Number.isFinite));
const completed=renderedPose();
for(const time of [900,1200,2000]) {
  advance(time);
  assertRenderedStable(renderedPose(),completed,`tiny completed focus stable at ${time}`);
}
''')

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
