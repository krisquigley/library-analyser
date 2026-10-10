"""Time-progressing delivery-adapter regressions; no browser/WebGL claims.

The vendor-probe tests separately validate bundled cameraPosition semantics. This
fixture models additive vendor transitions: a duration=0 write does not cancel
an existing timed write. Unlike immediate-call fixtures, advancing time exposes
stale camera and controls-target writes after a selection or orbit supersedes A.
"""
import shutil
import subprocess
import unittest

from tests.acceptance.test_explorer_selection_camera_integration import (
    ASSETS, FIXTURE, ROOT, FRAME_CLOCK_SEAM, replace_fixture_seam,
)


TIMED_FIXTURE = replace_fixture_seam(FIXTURE,
    'const frames = [], calls = [], requests = [], details = [];',
    '''const frames = [], calls = [], requests = [], details = [];
const transitions=[];
const listeners=new Map();''',
)
TIMED_FIXTURE = replace_fixture_seam(TIMED_FIXTURE,
    'const controls = {target:{x:0,y:0,z:0}};',
    '''const controls = {target:{x:0,y:0,z:0},
  addEventListener(type,fn){if(!listeners.has(type)) listeners.set(type,[]); listeners.get(type).push(fn);},
  removeEventListener(type,fn){listeners.set(type,(listeners.get(type)||[]).filter(value=>value!==fn));},
  update(){},
  dispatchEvent(event){for(const fn of listeners.get(event.type)||[]) fn(event);}};''',
)
TIMED_FIXTURE = replace_fixture_seam(TIMED_FIXTURE,
    'Object.assign(camera.position,position); Object.assign(controls.target,target);',
    '''if(duration>0) transitions.push({start:fixtureClock,duration,
      fromPosition:{...camera.position},fromTarget:{...controls.target},position:{...position},target:{...target}});
    else {Object.assign(camera.position,position); Object.assign(controls.target,target);}''',
)
TIMED_FIXTURE = replace_fixture_seam(TIMED_FIXTURE,
    FRAME_CLOCK_SEAM,
    "requestAnimationFrame:fn=>{frames.push(fn);return fn;},cancelAnimationFrame:fn=>{const index=frames.indexOf(fn);if(index>=0) frames.splice(index,1);},performance:{now:()=>fixtureClock},ResizeObserver,",
)
TIMED_FIXTURE = replace_fixture_seam(TIMED_FIXTURE,
    'function tick() {fixtureClock+=700; const pending=frames.splice(0); for(const callback of pending) callback(fixtureClock);}',
    '''function tick() {const pending=frames.splice(0); for(const callback of pending) callback(fixtureClock);}
function advance(milliseconds) {
  fixtureClock+=milliseconds;
  for(const tween of [...transitions]) {
    const progress=Math.min(1,(fixtureClock-tween.start)/tween.duration);
    for(const axis of ['x','y','z']) {
      camera.position[axis]=tween.fromPosition[axis]+(tween.position[axis]-tween.fromPosition[axis])*progress;
      controls.target[axis]=tween.fromTarget[axis]+(tween.target[axis]-tween.fromTarget[axis])*progress;
    }
    if(progress===1) transitions.splice(transitions.indexOf(tween),1);
  }
  tick();
}
function cameraSnapshot(){return {position:{...camera.position},target:{...controls.target}};}
async function startA() {
  render(); calls.length=0;
  const before=cameraSnapshot();
  await select('a'); tick(); advance(120);
  assert.notDeepEqual(cameraSnapshot(),before,'control: focus actually progresses before cancellation');
}''',
)


class CameraFixtureSeamTests(unittest.TestCase):
    def test_shared_clock_boundary_is_unique_and_adapted(self):
        self.assertEqual(FIXTURE.count(FRAME_CLOCK_SEAM), 1)
        self.assertNotIn(FRAME_CLOCK_SEAM, TIMED_FIXTURE)
        self.assertEqual(TIMED_FIXTURE.count('performance:{now:()=>fixtureClock}'), 1)
        self.assertEqual(TIMED_FIXTURE.count('cancelAnimationFrame:'), 1)

    def test_missing_or_duplicate_seam_fails_loudly(self):
        for fixture in ('absent boundary', 'seam seam'):
            with self.subTest(fixture=fixture):
                with self.assertRaisesRegex(ValueError, 'exactly once'):
                    replace_fixture_seam(fixture, 'seam', 'replacement')


class SelectionCameraCancellationTests(unittest.TestCase):
    def run_scenario(self, scenario):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Node required: RED must not be accepted via skipped tests')
        for asset in ASSETS:
            with self.subTest(asset=str(asset.relative_to(ROOT))):
                script = TIMED_FIXTURE + scenario + '\n})().then(()=>console.log("SCENARIO_COMPLETED")).catch(error=>{console.error(error);process.exitCode=1;});'
                result = subprocess.run([node, '-e', script, str(asset)], cwd=ROOT,
                                        capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('SCENARIO_COMPLETED', result.stdout)

    def test_focus_after_clock_advance_takes_full_700ms(self):
        self.run_scenario(r'''
render(); advance(2000);
const before=cameraSnapshot();
await select('b'); tick();
assert.deepEqual(cameraSnapshot(),before,'focus starts at current nonzero clock, not clock origin');
advance(350);
for(const axis of ['x','y','z'])
  assert.ok(Math.abs(controls.target[axis]-(before.target[axis]+(b['f'+axis]-before.target[axis])*0.5))<1e-9,
    'half elapsed duration means half target progress');
advance(349);
assert.notDeepEqual(cameraSnapshot().target,{x:b.fx,y:b.fy,z:b.fz},'not complete at 699ms');
advance(1);
assert.deepEqual(cameraSnapshot().target,{x:b.fx,y:b.fy,z:b.fz},'complete exactly at 700ms');
assert.equal(transitions.length,0,'adapter owns RAF duration, never vendor timed tweens');
''')

    def test_clock_and_cancel_raf_seam_after_elapsed_time(self):
        self.run_scenario(r'''
await startA();
assert.equal(run('performance.now()'),fixtureClock,'performance and RAF share one elapsed clock');
assert.equal(typeof context.cancelAnimationFrame,'function','fixture exposes cancellation boundary');
assert.ok(frames.length>0,'inflight focus has a pending RAF');
const pendingFocus=frames[frames.length-1];
const stopped=cameraSnapshot();
await select('missing');
assert.ok(!frames.includes(pendingFocus),'cancel removes pending focus RAF, not just generation-guards it');
advance(1000);
assert.deepEqual(cameraSnapshot(),stopped,'cancellation preserves both pose paths after deadline');
''')

    def test_unpositioned_selection_cancels_inflight_a_camera_and_target(self):
        self.run_scenario(r'''
await startA();
const afterA=cameraSnapshot();
await select('unpositioned'); tick();
assert.deepEqual(details,['a','unpositioned'],'detail remains independent of camera eligibility');
advance(120); advance(900);
assert.deepEqual(cameraSnapshot(),afterA,'A must stop writing both camera and controls target after unpositioned B');
''')

    def test_reset_cancels_inflight_a_camera_and_target(self):
        self.run_scenario(r'''
await startA();
const afterA=cameraSnapshot();
historyHook=()=>({current_track_id:null,history:[],selection_epoch:1});
await history('/api/reset');
assert.equal(run('getStateForTesting().current_track_id'),null);
advance(120); advance(900);
assert.deepEqual(cameraSnapshot(),afterA,'reset must stop A, not merely clear pending focus');
''')

    def test_new_selection_intent_cancels_before_post_acceptance(self):
        self.run_scenario(r'''
await startA();
const afterA=cameraSnapshot();
let resolvePost;
postHook=()=>new Promise(resolve=>{resolvePost=resolve;});
const pending=select('unpositioned');
advance(120); advance(900);
assert.deepEqual(cameraSnapshot(),afterA,'new selection intent cancels A while its POST is still pending');
resolvePost({ok:true,json:async()=>({current_track_id:'unpositioned',history:[],selection_epoch:0})});
await pending;
''')

    def test_reset_intent_cancels_before_post_acceptance(self):
        self.run_scenario(r'''
await startA();
const afterA=cameraSnapshot();
const originalFetch=context.fetch;
let resolveReset;
context.fetch=(path,options)=>path==='/api/reset'?new Promise(resolve=>{resolveReset=resolve;}):originalFetch(path,options);
const pending=run("applyHistorySelection('/api/reset')");
advance(120); advance(900);
assert.deepEqual(cameraSnapshot(),afterA,'reset intent cancels A while its POST is still pending');
authoritativeSnapshot={current_track_id:null,history:[],selection_epoch:1};
resolveReset({ok:true,json:async()=>authoritativeSnapshot});
for(let i=0;i<20;i++) {await Promise.resolve(); tick();}
await pending;
''')

    def test_user_orbit_start_cancels_inflight_a_camera_and_target(self):
        self.run_scenario(r'''
await startA();
controls.dispatchEvent({type:'start'});
Object.assign(camera.position,{x:901,y:802,z:703});
Object.assign(controls.target,{x:91,y:82,z:73});
const manual=cameraSnapshot();
advance(120); advance(900);
assert.deepEqual(cameraSnapshot(),manual,'inflight focus must never overwrite user orbit after controls start');
assert.deepEqual(details,['a']);
''')


if __name__ == '__main__':
    unittest.main()
