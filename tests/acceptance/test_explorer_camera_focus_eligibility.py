"""Actual vendor focus eligibility: skip unsafe norms before camera writes."""
import unittest

from tests.acceptance import test_explorer_camera_custom_bounds as bounds


class CameraFocusEligibilityTests(unittest.TestCase):
    run_actual_vendor = bounds.CameraCustomBoundsTests.run_actual_vendor

    def test_unsafe_actual_squared_offset_skips_before_camera_settlement(self):
        for coordinate, minimum, maximum in (
            ('0', '0', '1e-200'),
            ('0', '0', 'Number.MIN_VALUE'),
            ('1e-200', '0', '1e-200'),
            ('1e-161', '0', '1e-162'),
            ('0', '1e200', 'Infinity'),
        ):
            with self.subTest(coordinate=coordinate, minimum=minimum, maximum=maximum):
                self.run_actual_vendor(r'''
const selected=node('selected',0,0,0);
Object.assign(selected,{x:COORDINATE,fx:COORDINATE});
render(model([selected,b]));
Object.assign(controls,{enabled:false,minDistance:MINIMUM,maxDistance:MAXIMUM});
if(COORDINATE===1e-161) {
  // Match the adapter's actual operation order, not an idealized endpoint.
  const endpoint=selected.fx+MAXIMUM*selected.fx/Math.hypot(selected.fx,0,0);
  const offset=endpoint-selected.fx;
  assert.ok(offset>0,'nonorigin fixture has a representable noncoincident endpoint');
  assert.equal(offset*offset,0,'actual nonzero endpoint offset squares to zero');
}
controls.target.set(0,0,0); camera.position.set(400,400,400);
camera.up.set(0,1,0); camera.lookAt(controls.target);
const initial=renderedPose(), writesBefore=calls.length;
await select('selected');
assert.deepEqual(details,['selected'],'unsafe camera focus keeps accepted detail GET');
assert.equal(run('getStateForTesting().current_track_id'),'selected');
assert.equal(calls.length,writesBefore,'skip occurs before any camera settlement writes');
for(const time of [0,16,350,700,1200,2000]) {
  // Actual bundled tick gates Trackball.update on enabled. The shared orbit
  // fixture deliberately calls it unconditionally; reproduce disabled tick here.
  now=time; vendor.setTime(time); tick(); vendorState.tweenGroup.update(time);
  assert.equal(calls.length,writesBefore,`no delayed camera writes at ${time}`);
  assertRenderedStable(renderedPose(),initial,`skipped focus preserves rendered pose at ${time}`);
  assert.equal(controls.minDistance,MINIMUM,'custom minimum unchanged');
  assert.equal(controls.maxDistance,MAXIMUM,'custom maximum unchanged');
}
'''.replace('COORDINATE', coordinate).replace('MINIMUM', minimum).replace('MAXIMUM', maximum))

    def test_smallest_positive_squared_axis_norm_is_not_arbitrarily_skipped(self):
        for radius in ('Math.sqrt(Number.MIN_VALUE)', '2e-162'):
            with self.subTest(radius=radius):
                self.run_actual_vendor(r'''
const origin=node('origin',0,0,0);
render(model([origin,b]));
const radius=RADIUS;
assert.equal(radius*radius,Number.MIN_VALUE,'fixture has smallest positive squared norm');
Object.assign(controls,{enabled:false,minDistance:0,maxDistance:radius});
controls.target.set(0,0,0); camera.position.set(0,0,400);
camera.up.set(0,1,0); camera.lookAt(controls.target);
const expected=camera.quaternion.clone(), writesBefore=calls.length;
await select('origin');
now=700; vendor.setTime(now); tick(); vendorState.tweenGroup.update(now);
assert.deepEqual(details,['origin'],'border focus preserves detail GET');
assert.ok(calls.length>writesBefore,'positive squared norm remains focus eligible');
assert.deepEqual(pose().position,{x:0,y:0,z:radius},'exact eligible axis endpoint');
assert.ok([...camera.position.toArray(),...camera.quaternion.toArray()].every(Number.isFinite),
  'positive norm border pose is finite');
// Below sqrt(MIN_VALUE), rounded normalization need not give a unit quaternion.
// Only the exact square-root case promises the ordinary-scale quaternion oracle.
if(radius===Math.sqrt(Number.MIN_VALUE)) {
  assert.ok(camera.quaternion.angleTo(expected)<1e-7,'actual vendor exact-border direction is correct');
}
assert.equal(controls.maxDistance,radius,'border maximum unchanged');
'''.replace('RADIUS', radius))

    def test_subnormal_nonorigin_node_with_ordinary_radius_remains_focusable(self):
        self.run_actual_vendor(r'''
const selected=node('tiny',0,0,0);
Object.assign(selected,{x:Number.MIN_VALUE,fx:Number.MIN_VALUE});
render(model([selected,b]));
Object.assign(controls,{enabled:false,minDistance:0,maxDistance:2000});
const writesBefore=calls.length;
await select('tiny');
now=700; vendor.setTime(now); tick(); vendorState.tweenGroup.update(now);
assert.deepEqual(details,['tiny'],'subnormal selected coordinate preserves detail GET');
assert.ok(calls.length>writesBefore,'tiny node coordinate does not itself disqualify focus');
assert.deepEqual(pose().target,{x:Number.MIN_VALUE,y:0,z:0});
assert.deepEqual(pose().position,{x:100,y:0,z:0},'ordinary endpoint stays eligible');
''')


if __name__ == '__main__':
    unittest.main()
