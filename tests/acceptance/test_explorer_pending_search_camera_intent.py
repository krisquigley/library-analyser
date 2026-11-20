"""Actual registered search-result callbacks and bundled Trackball race regression."""
import shutil
import subprocess
import unittest

from tests.support.explorer_camera_harness import trackball_fixture
from tests.support.explorer_camera_harness import ASSETS, ROOT


SEARCH = r'''
// The listed search results, a then b, as the page drew them at startup.
const resultButton=index=>document.querySelectorAll('#tracks tbody tr')[index].querySelector('button');
const clickSearch=index=>resultButton(index).onclick();
function accepted(id) {return {ok:true,json:async()=>({current_track_id:id,history:[],selection_epoch:0})};}
function manualOrbit() {
  Object.assign(controls,{enabled:true,staticMoving:true,minDistance:350,maxDistance:600});
  camera.position.copy(controls.target).add(new vendor.THREE.Vector3(1,-0.4,0.3).normalize().multiplyScalar(450));
  camera.zoom=3.25; camera.updateProjectionMatrix(); controls.update();
  Object.assign(controls.screen,{left:0,top:0,width:800,height:600});
  controls._onMouseDown({button:0,pageX:400,pageY:300});
  controls._onMouseMove({pageX:425,pageY:315}); controls.update(); controls._onMouseUp();
}
function fullPose() {return {position:camera.position.toArray(),target:controls.target.toArray(),
  up:camera.up.toArray(),quaternion:camera.quaternion.toArray(),zoom:camera.zoom,
  settings:Object.fromEntries(['enabled','staticMoving','dynamicDampingFactor','rotateSpeed',
    'zoomSpeed','panSpeed','noZoom','noPan','noRotate','minDistance','maxDistance'].map(k=>[k,controls[k]]))};}
'''


class PendingSearchCameraIntentTests(unittest.TestCase):
    def run_scenario(self, scenario):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Node required; cannot skip RED')
        for asset in ASSETS:
            with self.subTest(asset=str(asset)):
                script = trackball_fixture() + SEARCH + scenario + (
                    '\n})().then(()=>console.log("SCENARIO_COMPLETED"))'
                    '.catch(error=>{console.error(error);process.exitCode=1;});')
                result = subprocess.run(['timeout', '--signal=KILL', '20s', node, '-e', script, str(asset)],
                                        cwd=ROOT, capture_output=True, text=True, timeout=25)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('SCENARIO_COMPLETED', result.stdout)

    def test_pending_registered_search_manual_orbit_then_accept_updates_detail_not_camera(self):
        self.run_scenario(r'''
await render(); let resolvePost; postHook=()=>new Promise(resolve=>{resolvePost=resolve;});
const pending=clickSearch(0); assert.equal(requests.at(-1).path,'/api/current');
manualOrbit(); const manual=fullPose();
resolvePost(accepted('a')); await pending;
assert.deepEqual(details,['a'],'authoritative acceptance still fetches detail'); assertHalo('a');
for(const time of [0,100,350,700,1200]) {
  advance(time); assert.deepEqual(fullPose(),manual,'late acceptance must not reclaim manual camera intent');
}
assert.equal(seam.snapshot().cameraFocusActive,false);
''')

    def test_normal_registered_search_still_finishes_focus_at_700ms(self):
        self.run_scenario(r'''
await render(); await clickSearch(0); advance(0);
for(const time of [100,350,699]) {
  advance(time); assert.notDeepEqual(pose().target,{x:a.fx,y:a.fy,z:a.fz},'normal focus remains animated before700');
}
advance(700); assert.deepEqual(pose().target,{x:a.fx,y:a.fy,z:a.fz}); assertHalo('a');
''')

    def test_manual_orbit_retires_accepted_focus_waiting_for_layout(self):
        self.run_scenario(r'''
await render(); byId('reload-graph').onclick(); await flush();
assert.equal(seam.snapshot().graphStatus,'loading','a reload is waiting for the graph');
await clickSearch(0); assertHalo('a'); manualOrbit(); const manual=fullPose();
await render();
advance(0); advance(700); assert.deepEqual(fullPose(),manual);
''')

    def test_graph_reload_receipt_while_post_pending_retires_old_search_focus(self):
        self.run_scenario(r'''
await render(); let resolvePost; postHook=()=>new Promise(resolve=>{resolvePost=resolve;});
const pending=clickSearch(0);
byId('reload-graph').onclick(); await flush();
resolvePost(accepted('a')); await pending; assert.deepEqual(details,['a']);
await render();
controls.update(); const prior=fullPose(); advance(0); advance(700); assert.deepEqual(fullPose(),prior);
''')

    def test_graph_filter_receipt_while_post_pending_retires_old_search_focus(self):
        self.run_scenario(r'''
await render(); let resolvePost; postHook=()=>new Promise(resolve=>{resolvePost=resolve;});
const pending=clickSearch(0); byId('clear-graph-filters').onclick();
resolvePost(accepted('a')); await pending; assert.deepEqual(details,['a']); assertHalo('a');
controls.update(); const prior=fullPose(); advance(0); advance(700); assert.deepEqual(fullPose(),prior);
''')

    def test_reset_retires_delayed_registered_search(self):
        self.run_scenario(r'''
await render(); let resolveA; postHook=()=>new Promise(resolve=>{resolveA=resolve;});
const pending=clickSearch(0);
historyHook=()=>({current_track_id:null,history:[],selection_epoch:1});
await history('/api/reset'); resolveA(accepted('a')); await pending;
assert.deepEqual(details,[]);assert.equal(seam.snapshot().currentTrackId,null);
controls.update();const prior=fullPose();advance(0);advance(700);assert.deepEqual(fullPose(),prior);
''')

    def test_newer_registered_search_retires_delayed_a(self):
        self.run_scenario(r'''
await render(); let resolveA;
postHook=id=>id==='a'?new Promise(resolve=>{resolveA=resolve;}):Promise.resolve(accepted(id));
const pending=clickSearch(0); await clickSearch(1); resolveA(accepted('a')); await pending;
advance(0);advance(700); assert.deepEqual(details,['b']);assertHalo('b');
assert.deepEqual(pose().target,{x:b.fx,y:b.fy,z:b.fz});
''')


if __name__ == '__main__':
    unittest.main()
