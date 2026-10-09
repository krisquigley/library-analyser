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
    ASSETS, FIXTURE, ROOT,
)


TIMED_FIXTURE = FIXTURE.replace(
    'const frames = [], calls = [], requests = [], details = [];',
    '''const frames = [], calls = [], requests = [], details = [];
let clock=0;
const transitions=[];
const listeners=new Map();''',
).replace(
    'const controls = {target:{x:0,y:0,z:0}};',
    '''const controls = {target:{x:0,y:0,z:0},
  addEventListener(type,fn){if(!listeners.has(type)) listeners.set(type,[]); listeners.get(type).push(fn);},
  removeEventListener(type,fn){listeners.set(type,(listeners.get(type)||[]).filter(value=>value!==fn));},
  update(){},
  dispatchEvent(event){for(const fn of listeners.get(event.type)||[]) fn(event);}};''',
).replace(
    'Object.assign(camera.position,position); Object.assign(controls.target,target);',
    '''if(duration>0) transitions.push({start:clock,duration,
      fromPosition:{...camera.position},fromTarget:{...controls.target},position:{...position},target:{...target}});
    else {Object.assign(camera.position,position); Object.assign(controls.target,target);}''',
).replace(
    "requestAnimationFrame:fn=>{frames.push(fn);return frames.length;},ResizeObserver,",
    "requestAnimationFrame:fn=>{frames.push(fn);return fn;},cancelAnimationFrame:fn=>{const index=frames.indexOf(fn);if(index>=0) frames.splice(index,1);},performance:{now:()=>clock},ResizeObserver,",
).replace(
    'function tick() {fixtureClock+=700; const pending=frames.splice(0); for(const callback of pending) callback(fixtureClock);}',
    '''function tick() {const pending=frames.splice(0); for(const callback of pending) callback(clock);}
function advance(milliseconds) {
  clock+=milliseconds;
  for(const tween of [...transitions]) {
    const progress=Math.min(1,(clock-tween.start)/tween.duration);
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
