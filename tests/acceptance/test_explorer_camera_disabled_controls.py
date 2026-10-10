"""Disabled selection focus using the actual bundled setter and Trackball.

The vendor's disabled setter looks at the supplied point without updating the
public orbit target. The adapter must keep that target synchronized so both
render-loop updates and subsequent re-enabling retain the rendered orientation.
"""
import unittest

from tests.acceptance import test_explorer_camera_unflushed_damping as damping


class CameraDisabledControlsTests(unittest.TestCase):
    # Reuse the hard-SIGKILL actual-vendor runner, including its input helpers.
    run_scenario = damping.CameraUnflushedDampingTests.run_scenario
    def test_actual_vendor_disabled_setter_leaves_orbit_target_stale(self):
        self.run_scenario(r'''
render(); manualStart();
controls.enabled=false;
const oldTarget=controls.target.clone();
const position={x:501,y:402,z:303}, target={x:51,y:42,z:33};
vendor.cameraPosition(vendorState,position,target,0);
assert.ok(controls.target.distanceTo(oldTarget)<1e-9,
  'bundled disabled camera setter leaves public target stale');
const expected=camera.clone(); expected.lookAt(new vendor.THREE.Vector3(target.x,target.y,target.z));
assert.ok(camera.quaternion.angleTo(expected.quaternion)<1e-7,
  'bundled disabled setter renders the requested look-at');
const rendered=camera.quaternion.clone();
controls.update();
assert.ok(camera.quaternion.angleTo(rendered)>0.01,
  'actual Trackball update redirects orientation to stale orbit target');
''')

    def test_disabled_focus_syncs_target_and_survives_reenable_with_pending_input(self):
        for input_name in ('none', 'unflushedWheel', 'unflushedPan', 'unflushedOrbit'):
            with self.subTest(input=input_name):
                self.run_scenario(r'''
render(); manualStart(); INPUT();
const config={enabled:false,staticMoving:false,dynamicDampingFactor:0.37,
  rotateSpeed:1.3,zoomSpeed:1.7,panSpeed:0.6,noZoom:true,noPan:true,noRotate:true,
  minDistance:0.25,maxDistance:2000};
Object.assign(controls,config);
const settings=()=>Object.fromEntries(Object.keys(config).map(key=>[key,controls[key]]));
const initial=renderedPose();
await select('a');
assert.deepEqual(settings(),config,'selection restores all public settings including disabled');
assertRenderedStable(renderedPose(),initial,'disabled selection preserves starting rendered pose');
advance(0);
assertRenderedStable(renderedPose(),initial,'elapsed zero preserves disabled rendered pose');
for(const time of [100,350,695,700,900,1200]) {
  advance(time);
  assert.deepEqual(settings(),config,`disabled settings unchanged at ${time}`);
  const requestedTarget=calls.at(-1).target;
  assert.deepEqual(pose().target,requestedTarget,
    `disabled public orbit target matches requested look-at at ${time}`);
  // Independently compare the post-update orientation to the requested target.
  const expected=camera.clone();
  expected.lookAt(new vendor.THREE.Vector3(requestedTarget.x,requestedTarget.y,requestedTarget.z));
  assert.ok(camera.quaternion.angleTo(expected.quaternion)<1e-7,
    `rendered quaternion agrees with synchronized orbit target at ${time}`);
  if(time>=700) {assertEndpoint(`disabled endpoint ${time}`); assertRadialEndpoint(a,`disabled endpoint ${time}`);}
}
const completed=renderedPose();
Object.assign(controls,{enabled:true,noZoom:false,noPan:false,noRotate:false});
for(const time of [1216,1232,1300,2000]) {
  advance(time);
  assertRenderedStable(renderedPose(),completed,`reenabled pose at ${time}`);
}
// Re-enabled controls retain configured dynamics and support fresh manual input.
const focused=renderedPose(); unflushedOrbit();
assert.ok(camera.position.distanceTo(focused.position)>1,'fresh re-enabled orbit moves camera');
const manual=renderedPose(); advance(2016);
assert.ok(camera.position.distanceTo(manual.position)>1e-3,
  'fresh dynamic damping remains enabled after disabled focus');
'''.replace('INPUT()', '' if input_name == 'none' else input_name + '()'))


if __name__ == '__main__':
    unittest.main()
