"""Time-stepped camera tests using bundled THREE, TWEEN and cameraPosition.

The bundle is evaluated with a test-only export at its closure boundary. Its
camera method and tween implementation are neither rewritten nor mocked. No
renderer, WebGL, database or wall-clock animation is involved.
"""
import re
import shutil
import subprocess
import unittest

from tests.acceptance.test_explorer_selection_camera_integration import ASSETS, FIXTURE, ROOT


VENDOR = r'''
const vendor = (() => {
  const fs = require('node:fs'), vm = require('node:vm');
  const path = require('node:path').join(require('node:path').dirname(process.argv[1]),
    'vendor/3d-force-graph/3d-force-graph.min.js');
  let source = fs.readFileSync(path, 'utf8').trimEnd();
  const start = source.indexOf('cameraPosition:function(e,t,n,i)');
  const end = source.indexOf(',zoomToFit:', start);
  if (start < 0 || end < 0) throw new Error('Bundled camera seam changed; review harness');
  const method = source.slice(start + 'cameraPosition:'.length, end);
  const boundary = 'return Ok});';
  if (!source.endsWith(boundary)) throw new Error('Bundled closure changed; review harness');
  source = source.slice(0, -boundary.length) +
    `globalThis.cameraTestExports={Group:oO,THREE:Ak,cameraPosition:${method}};` + boundary;
  let now = 0;
  const context = vm.createContext({console, setTimeout, clearTimeout, setInterval,
    clearInterval, window:{}, performance:{now:()=>now}});
  vm.runInContext(source, context, {filename:path});
  return {...context.cameraTestExports, setTime:value=>{now=value;}};
})();
let now=0, frameId=0;
const cancelledFrames=new Set();
const vendorCamera=new vendor.THREE.PerspectiveCamera();
vendorCamera.position.set(500,400,300);
// THREE camera inherits the bundled event dispatcher used by controls; no renderer needed.
const vendorControls=Object.assign(new vendor.THREE.PerspectiveCamera(),
  {enabled:true,target:new vendor.THREE.Vector3()});
const vendorState={initialised:true,camera:vendorCamera,controls:vendorControls,
  tweenGroup:new vendor.Group()};
'''


def real_vendor_fixture():
    fixture = FIXTURE.replace(
        "const camera = {fov:50,position:{x:500,y:400,z:300}};\nconst controls = {target:{x:0,y:0,z:0}};",
        "const camera=vendorCamera; camera.fov=50; const controls=vendorControls;")
    fixture = fixture.replace(
        "Object.assign(camera.position,position); Object.assign(controls.target,target);",
        "vendor.cameraPosition(vendorState,position,target,duration);")
    fixture = re.sub(r'performance:\{now:\(\)=>fixtureClock\},', '', fixture)
    fixture = fixture.replace(
        "requestAnimationFrame:fn=>{frames.push(fn);return frames.length;},ResizeObserver,", 
        "performance:{now:()=>now}, requestAnimationFrame:fn=>{const id=++frameId;\n"
        "    frames.push(time=>{if(!cancelledFrames.has(id)) fn(time);});return id;},\n"
        "  cancelAnimationFrame:id=>cancelledFrames.add(id),ResizeObserver,")
    fixture = re.sub(
        r'function tick\(\) \{[^\n]*\}',
        "function tick() {const pending=frames.splice(0); for(const callback of pending) callback();}",
        fixture,
    )
    fixture = fixture.replace(
        "function tick() {const pending=frames.splice(0); for(const callback of pending) callback();}",
        "function tick() {const pending=frames.splice(0); for(const callback of pending) if(callback) callback(now);}\n"
        "function advance(time) {now=time; vendor.setTime(time); tick(); vendorState.tweenGroup.update(time);}\n"
        "function pose() {return {position:{x:camera.position.x,y:camera.position.y,z:camera.position.z},\n"
        "  target:{x:controls.target.x,y:controls.target.y,z:controls.target.z}};}")
    return VENDOR + fixture


class CameraVendorCancellationTests(unittest.TestCase):
    def run_scenario(self, scenario):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Node required; do not skip RED')
        for asset in ASSETS:
            with self.subTest(asset=str(asset.relative_to(ROOT))):
                script = real_vendor_fixture() + scenario + (
                    '\n})().then(()=>console.log("SCENARIO_COMPLETED"))'
                    '.catch(error=>{console.error(error);process.exitCode=1;});')
                result = subprocess.run([node, '-e', script, str(asset)], cwd=ROOT,
                                        capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('SCENARIO_COMPLETED', result.stdout)

    def test_vendor_zero_duration_setter_does_not_cancel_existing_tweens(self):
        self.run_scenario(r'''
vendor.cameraPosition(vendorState,{x:100,y:0,z:0},{x:20,y:0,z:0},700);
advance(100);
assert.equal(vendorState.tweenGroup.getAll().length,2);
vendor.cameraPosition(vendorState,{x:5,y:6,z:7},{x:8,y:9,z:10},0);
assert.equal(camera.position.x,5);
advance(200);
assert.notEqual(camera.position.x,5,'actual vendor tween overwrites instant setter');
assert.notEqual(controls.target.x,8,'actual vendor target tween also survives');
''')

    def test_missing_selection_cancels_motion_without_later_vendor_overwrite(self):
        self.run_scenario(r'''
render(); await select('a'); advance(0); advance(100);
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
render(data); await select('a'); advance(0); advance(100);
const stopped=pose();
await select('unpositioned'); advance(200); advance(800); advance(1200);
assert.deepEqual(pose(),stopped,'unpositioned selection cancels both real vendor write paths');
assert.deepEqual(details,['a','unpositioned']);
assert.equal(vendorState.tweenGroup.getAll().length,0);
''')

    def test_user_orbit_start_cancels_motion_and_preserves_manual_pose(self):
        self.run_scenario(r'''
render(); await select('a'); advance(0); advance(100);
controls.dispatchEvent({type:'start'});
camera.position.set(901,802,703); controls.target.set(91,82,73);
const manual=pose();
advance(200); advance(800); advance(1200);
assert.deepEqual(pose(),manual,'user orbit cannot be overwritten after old focus deadline');
assert.equal(vendorState.tweenGroup.getAll().length,0);
''')

    def test_reset_cancels_motion_and_preserves_manual_pose_past_old_deadline(self):
        self.run_scenario(r'''
render(); await select('a'); advance(0); advance(100);
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
render(); await select('a'); advance(0); const initial=pose(); advance(100);
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
