"""Additional issue #84 authority checks at the real asset callback boundary."""
import unittest

from tests.acceptance import test_explorer_graph_click_immediate as immediate


class GraphClickAuthorityTests(unittest.TestCase):
    run_scenario = immediate.GraphClickImmediateTests.run_scenario

    def test_click_uses_mounted_geometry_and_cancels_queued_search_before_post(self):
        self.run_scenario(r'''
render(); configureView(); calls.length=0;
await searchButton('a').onclick(); await flush();
assert.equal(calls.length,0,'search animation is queued but has not run');
let resolvePost, postPose;
postHook=()=>{
  postPose=pose();
  return new Promise(resolve=>{resolvePost=resolve;});
};
const before=pose();
// A pick's transient coordinates are not authoritative: use mounted layout.
const pending=clickHandler({...b,fx:999,fy:999,fz:999});
assert.deepEqual(postPose,translated(before,b),'camera pose is applied before selection POST');
assertImmediate(before,b);
const clicked=pose(), count=calls.length;
tick(); tick();
assert.deepEqual(pose(),clicked,'queued search cannot override immediate click');
resolvePost(accept('b')); await pending; await flush(); tick(); tick();
assert.deepEqual(pose(),clicked); assert.equal(calls.length,count);
assert.deepEqual(details,['a','b']); assertHalo('b');
''')

    def test_history_and_replacement_own_view_after_pending_graph_click(self):
        for action in ('undo', 'reset', 'replacement'):
            with self.subTest(action=action):
                self.run_scenario("const action=" + repr(action) + r''';
render(); configureView(); calls.length=0;
let resolvePost;
postHook=()=>new Promise(resolve=>{resolvePost=resolve;});
const pending=clickHandler(b);
if(action==='replacement') {
  render(model([node('a',0.8,0.7,0.6),node('b',0.6,0.4,0.2)]));
} else {
  historyHook=()=>({current_track_id:action==='undo'?'a':null,history:[],selection_epoch:1});
  await history('/api/'+action);
}
await flush(); tick(); tick();
const owned=pose(), count=calls.length, loaded=[...details];
resolvePost(accept('b')); await pending; await flush(); tick(); tick();
assert.deepEqual(pose(),owned,'late graph POST cannot override newer view authority');
assert.equal(calls.length,count,'late graph acceptance never replays camera focus');
if(action!=='replacement') assert.deepEqual(details,loaded,'history supersedes graph detail authority');
''')

    def test_render_gap_uses_mounted_coordinates_not_pending_layout(self):
        self.run_scenario(r'''
render(); configureView(); calls.length=0;
const before=pose();
context.pendingLayout=model([node('a',0.8,0.7,0.6),node('b',0.6,0.4,0.2)]);
run("setVisibleGraphForTesting(pendingLayout); graphLoadState={...graphLoadState,status:'rendering'}");
let resolvePost; postHook=()=>new Promise(resolve=>{resolvePost=resolve;});
const pending=clickHandler(b);
assertImmediate(before,b);
resolvePost(accept('b')); await pending; await flush(); tick(); tick();
assert.deepEqual(pose(),translated(before,b),'acceptance cannot focus unmounted replacement');
''')

    def test_unrepresentable_translation_skips_pose_and_adapter_error_keeps_selection(self):
        self.run_scenario(r'''
const enormous=node('enormous'); Object.assign(enormous,{fx:1e100,fy:1e100,fz:1e100});
render(model([a,b,enormous])); configureView(); calls.length=0;
const before=pose();
await clickHandler(enormous); await flush(); tick(); tick();
assert.deepEqual(pose(),before,'finite but degenerate translated pose is not usable geometry');
assert.equal(calls.length,0); assert.deepEqual(details,['enormous']);
context.brokenGraph=new Proxy(graph,{get(target,key){
  if(key==='cameraPosition') return ()=>{throw new Error('fixture camera unavailable');};
  return Reflect.get(target,key);
}});
run('forceGraph=brokenGraph');
let pending; assert.doesNotThrow(()=>{pending=clickHandler(a);});
await pending; await flush(); tick(); tick();
assert.deepEqual(details,['enormous','a'],'adapter failure cannot revoke accepted detail');
assert.deepEqual(pose(),before);
''')
