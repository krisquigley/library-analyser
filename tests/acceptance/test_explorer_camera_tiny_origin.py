"""Tiny origin focus must not inherit bundled THREE lookAt norm underflow.

Use the actual bundled setter/THREE/Trackball, not a replacement lookAt. An
independent ordinary-scale camera supplies the quaternion oracle. Safe skipping
of an unrenderable focus is allowed, but never a wrong rendered orientation or
suppression of the accepted selection's independent detail GET.
"""
import unittest

from tests.acceptance import test_explorer_camera_custom_bounds as bounds


class CameraTinyOriginTests(unittest.TestCase):
    def run_actual_vendor(self, scenario):
        # Inline scripts leave no scratch files; timeout sends SIGKILL at 20s.
        # The orbit fixture intentionally updates controls even when disabled.
        # Actual bundled tick gates that update on enabled: reproduce its gate
        # without replacing THREE.lookAt, Trackball, or the camera setter.
        inputs = bounds.INPUTS + r'''
advance=function(time) {
  now=time; vendor.setTime(time); tick(); vendorState.tweenGroup.update(time);
  if(controls.enabled) controls.update();
};
'''
        bounds.CameraCustomBoundsTests.run_actual_vendor(self, scenario, inputs=inputs)

    def test_disabled_tiny_origin_preserves_actual_rendered_view_direction(self):
        for maximum in ('1e-200', 'Number.MIN_VALUE'):
            with self.subTest(maximum=maximum):
                self.run_actual_vendor(r'''
const origin=node('origin',0,0,0);
render(model([origin,b]));
Object.assign(controls,{enabled:false,minDistance:0,maxDistance:MAXIMUM});
controls.target.set(0,0,0);
camera.position.set(400,400,400);
camera.up.set(0,1,0);
// Establish an ordinary-scale rendered pose before attempting tiny origin focus.
camera.lookAt(controls.target);
const initial=renderedPose();
const expected=camera.clone();
expected.position.set(1,1,1);
expected.lookAt(new vendor.THREE.Vector3(0,0,0));
assert.ok(initial.quaternion.angleTo(expected.quaternion)<1e-7,
  'ordinary-scale oracle matches the actual starting diagonal view');
await select('origin');
assert.deepEqual(details,['origin'],'accepted origin selection still requests independent detail GET');
assert.equal(run('getStateForTesting().current_track_id'),'origin');
assertRenderedStable(renderedPose(),initial,'selection preserves rendered start');
for(const time of [0,16,100,350,695,700,900,1200,2000]) {
  advance(time);
  assert.equal(controls.enabled,false,`disabled controls retained at ${time}`);
  assert.equal(controls.minDistance,0,`custom minimum retained at ${time}`);
  assert.equal(controls.maxDistance,MAXIMUM,`tiny custom maximum never widened at ${time}`);
  assert.ok([...camera.position.toArray(),...controls.target.toArray(),
    ...camera.up.toArray(),...camera.quaternion.toArray()].every(Number.isFinite),
    `rendered pose remains finite at ${time}`);
  // Origin focus has no angular change. A safe skipped focus also retains this
  // direction. Compare quaternions, not underflow-prone squared distances.
  const error=camera.quaternion.angleTo(expected.quaternion);
  assert.ok(error<1e-7,
    `tiny origin rendered direction at ${time}: quaternion error ${error} radians`);
}
assert.deepEqual(details,['origin'],'camera focus never repeats or suppresses detail GET');
assert.equal(vendorState.tweenGroup.getAll().length,0,'no private vendor tween remains');
'''.replace('MAXIMUM', maximum))


if __name__ == '__main__':
    unittest.main()
