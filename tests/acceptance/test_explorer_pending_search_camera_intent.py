"""Actual registered search-result callbacks and bundled Trackball race regression."""
import shutil
import subprocess
import unittest

from tests.acceptance.test_explorer_camera_orbit_path import trackball_fixture
from tests.acceptance.test_explorer_selection_camera_integration import ASSETS, ROOT


SEARCH = r'''
elements.tracks=new Element();
context.searchResults=[{handle:'a',title:'A',artist:'Public synthetic'},
  {handle:'b',title:'B',artist:'Public synthetic'}];
run('renderTracks(searchResults)');
const resultButton=index=>elements.tracks.children[0].children[2].children[index].children[0].children[0];
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
            with self.subTest(asset=str(asset.relative_to(ROOT))):
                script = trackball_fixture() + SEARCH + scenario + (
                    '\n})().then(()=>console.log("SCENARIO_COMPLETED"))'
                    '.catch(error=>{console.error(error);process.exitCode=1;});')
                result = subprocess.run(['timeout', '--signal=KILL', '20s', node, '-e', script, str(asset)],
                                        cwd=ROOT, capture_output=True, text=True, timeout=25)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('SCENARIO_COMPLETED', result.stdout)

    def test_pending_registered_search_manual_orbit_then_accept_updates_detail_not_camera(self):
        self.run_scenario(r'''
render(); let resolvePost; postHook=()=>new Promise(resolve=>{resolvePost=resolve;});
const pending=clickSearch(0); assert.equal(requests.at(-1).path,'/api/current');
manualOrbit(); const manual=fullPose();
resolvePost(accepted('a')); await pending;
assert.deepEqual(details,['a'],'authoritative acceptance still fetches detail'); assertHalo('a');
for(const time of [0,100,350,700,1200]) {
  advance(time); assert.deepEqual(fullPose(),manual,'late acceptance must not reclaim manual camera intent');
}
assert.equal(run('cameraFocusFrame'),null);
''')

    def test_normal_registered_search_still_finishes_focus_at_700ms(self):
        self.run_scenario(r'''
render(); await clickSearch(0); advance(0);
for(const time of [100,350,699]) {
  advance(time); assert.notDeepEqual(pose().target,{x:a.fx,y:a.fy,z:a.fz},'normal focus remains animated before700');
}
advance(700); assert.deepEqual(pose().target,{x:a.fx,y:a.fy,z:a.fz}); assertHalo('a');
''')

    def test_manual_orbit_retires_accepted_focus_waiting_for_layout(self):
        self.run_scenario(r'''
render(); run("graphLoadState={...graphLoadState,status:'loading'}");
await clickSearch(0); assertHalo('a'); manualOrbit(); const manual=fullPose();
run("graphLoadState={...graphLoadState,status:'ready'}; focusPendingCameraSelection()");
advance(0); advance(700); assert.deepEqual(fullPose(),manual);
''')

    def test_graph_reload_receipt_while_post_pending_retires_old_search_focus(self):
        self.run_scenario(r'''
render(); let resolvePost; postHook=()=>new Promise(resolve=>{resolvePost=resolve;});
const pending=clickSearch(0);
graphHook=()=>new Promise(()=>{}); run('loadGraph()');
resolvePost(accepted('a')); await pending; assert.deepEqual(details,['a']);
run("graphLoadState={...graphLoadState,status:'ready'}; focusPendingCameraSelection()");
controls.update(); const prior=fullPose(); advance(0); advance(700); assert.deepEqual(fullPose(),prior);
''')

    def test_graph_filter_receipt_while_post_pending_retires_old_search_focus(self):
        self.run_scenario(r'''
render(); let resolvePost; postHook=()=>new Promise(resolve=>{resolvePost=resolve;});
const pending=clickSearch(0); run('applyCurrentGraphFilters()');
resolvePost(accepted('a')); await pending; assert.deepEqual(details,['a']); assertHalo('a');
controls.update(); const prior=fullPose(); advance(0); advance(700); assert.deepEqual(fullPose(),prior);
''')

    def test_reset_retires_delayed_registered_search(self):
        self.run_scenario(r'''
render(); let resolveA; postHook=()=>new Promise(resolve=>{resolveA=resolve;});
const pending=clickSearch(0);
historyHook=()=>({current_track_id:null,history:[],selection_epoch:1});
await history('/api/reset'); resolveA(accepted('a')); await pending;
assert.deepEqual(details,[]);assert.equal(run('state.current_track_id'),null);
controls.update();const prior=fullPose();advance(0);advance(700);assert.deepEqual(fullPose(),prior);
''')

    def test_newer_registered_search_retires_delayed_a(self):
        self.run_scenario(r'''
render(); let resolveA;
postHook=id=>id==='a'?new Promise(resolve=>{resolveA=resolve;}):Promise.resolve(accepted(id));
const pending=clickSearch(0); await clickSearch(1); resolveA(accepted('a')); await pending;
advance(0);advance(700); assert.deepEqual(details,['b']);assertHalo('b');
assert.deepEqual(pose().target,{x:b.fx,y:b.fy,z:b.fz});
''')


if __name__ == '__main__':
    unittest.main()
