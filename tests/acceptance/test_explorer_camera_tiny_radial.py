"""Tiny non-origin coordinates retain radial focus with the actual bundled THREE.

The radius is renderable even when radius * coordinate underflows. Exercise both
mirrors without replacing lookAt, Trackball, or cameraPosition; detail is separate.
"""
import unittest

from tests.acceptance import test_explorer_camera_tiny_origin as tiny_origin


class CameraTinyRadialTests(unittest.TestCase):
    def run_actual_vendor(self, scenario):
        tiny_origin.CameraTinyOriginTests.run_actual_vendor(self, scenario)

    def test_tiny_non_origin_with_renderable_custom_radius_focuses_radially(self):
        for coordinate, radius in (
            ('1e-200', 'Math.sqrt(2**-1022)*(1+1e-8)'),
            ('Number.MIN_VALUE', '0.5'),
            ('Number.MIN_VALUE*200', '0.001'),
            ('Number.MIN_VALUE', '1e-100'),
            ('1e-200', '1e-150'),
        ):
            with self.subTest(coordinate=coordinate, radius=radius):
                self.run_radial(coordinate, radius)

    def test_ordinary_non_origin_retains_normal_radial_behavior(self):
        self.run_radial('3', '60')

    def run_radial(self, coordinate, radius):
        self.run_actual_vendor(r'''
const selected=node('tiny',0,0,0);
// node() normally converts fixture coordinates to display space by *200.
// Set the actual positioned coordinate explicitly to test the subnormal itself.
selected.x=selected.fx=COORDINATE;
render(model([selected,b]));
Object.assign(controls,{enabled:false,minDistance:0,maxDistance:RADIUS});
controls.target.set(0,0,0);
camera.position.set(400,400,400);
camera.up.set(0,1,0);
camera.lookAt(controls.target);
const initial=renderedPose();
await select('tiny');
assert.deepEqual(details,['tiny'],'accepted selection independently requests detail');
assert.equal(run('getStateForTesting().current_track_id'),'tiny');
assertRenderedStable(renderedPose(),initial,'selection does not jump rendered pose');
for(const time of [0,16,100,350,695,700,900,1200,2000]) {
  advance(time);
  assert.equal(controls.enabled,false,'disabled controls retained');
  assert.equal(controls.minDistance,0,'custom minimum retained');
  assert.equal(controls.maxDistance,RADIUS,'custom radius never widened');
  assert.ok([...camera.position.toArray(),...controls.target.toArray(),
    ...camera.up.toArray(),...camera.quaternion.toArray()].every(Number.isFinite),
    `finite actual rendered pose at ${time}`);
  if(time>=700) {
    assert.deepEqual(pose().target,{x:selected.fx,y:0,z:0},'exact selected target reached');
    const offset=camera.position.clone().sub(new vendor.THREE.Vector3(selected.fx,0,0));
    assert.ok(Math.abs(offset.x/RADIUS-1)<1e-12,'renderable custom radial radius reached');
    assert.equal(offset.y,0,'radial endpoint has no Y offset');
    assert.equal(offset.z,0,'radial endpoint has no Z offset');
    const oracle=camera.clone();
    oracle.position.set(1,0,0); oracle.lookAt(new vendor.THREE.Vector3(0,0,0));
    assert.ok(camera.quaternion.angleTo(oracle.quaternion)<1e-7,
      'actual bundled lookAt renders the radial +X direction');
  }
}
assert.deepEqual(details,['tiny'],'focus does not repeat detail');
assert.equal(vendorState.tweenGroup.getAll().length,0,'no private vendor tween remains');
'''.replace('COORDINATE', coordinate).replace('RADIUS', '(' + radius + ')'))

    def test_tiny_origin_custom_bounds_still_safely_skip(self):
        for radius in ('Number.MIN_VALUE', '1e-200'):
            with self.subTest(radius=radius):
                self.run_actual_vendor(r'''
const origin=node('origin',0,0,0);
render(model([origin,b]));
Object.assign(controls,{enabled:false,minDistance:0,maxDistance:RADIUS});
controls.target.set(0,0,0); camera.position.set(400,400,400);
camera.up.set(0,1,0); camera.lookAt(controls.target);
const initial=renderedPose(), initialCalls=calls.length;
await select('origin');
for(const time of [0,16,100,350,695,700,900,2000]) {
  advance(time);
  assertRenderedStable(renderedPose(),initial,'unrenderable origin focus safely skipped');
  assert.equal(calls.length,initialCalls,'no unsafe camera setter requested');
  assert.equal(controls.maxDistance,RADIUS,'tiny custom bound never widened');
}
assert.deepEqual(details,['origin'],'skipped focus still requests accepted detail');
'''.replace('RADIUS', radius))

    def test_ordinary_origin_preserves_view_with_representable_custom_radius(self):
        self.run_actual_vendor(r'''
const origin=node('origin',0,0,0);
render(model([origin,b]));
Object.assign(controls,{enabled:false,minDistance:0,maxDistance:60});
controls.target.set(0,0,0); camera.position.set(400,400,400);
camera.up.set(0,1,0); camera.lookAt(controls.target);
const initial=renderedPose();
await select('origin');
for(const time of [0,16,100,350,695,700,900,2000]) {
  advance(time);
  assert.ok(camera.quaternion.angleTo(initial.quaternion)<1e-7,'origin keeps view direction');
  assert.equal(controls.maxDistance,60,'origin retains bounds');
  if(time>=700) {
    assert.deepEqual(pose().target,{x:0,y:0,z:0});
    assert.ok(Math.abs(camera.position.length()-60)<1e-10,'ordinary origin focuses');
  }
}
assert.deepEqual(details,['origin'],'origin detail stays independent');
''')


if __name__ == '__main__':
    unittest.main()
