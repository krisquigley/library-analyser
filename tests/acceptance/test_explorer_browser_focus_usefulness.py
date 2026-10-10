"""Default observer contracts, NOT real-browser useful-focus acceptance.

Controlled JavaScript executes the actual diagnostic expressions. No Chromium,
WebGL evidence, subjective size band, responsiveness budget, or calibration is
claimed. The aspect/FOV values below are observation cases, not an owner-agreed
supported range. Owner agreement and a separately bounded real-browser review
remain necessary for useful/smooth focus acceptance.
"""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
from threading import Event
import unittest

from tools import explorer_browser_diagnostic as diagnostic
from tools.explorer_browser_report import publish_browser_report
from tests.unit.benchmark_tools.test_explorer_browser_phase_attribution import _observer_scripts
from tests.unit.benchmark_tools.test_explorer_focus_projection_observation import _run_readback


def _node():
    executable = shutil.which('node') or shutil.which('nodejs')
    if executable:
        return executable
    spec = importlib.util.find_spec('playwright')
    if spec and spec.origin:
        bundled = Path(spec.origin).parent / 'driver' / 'node'
        if bundled.is_file():
            return str(bundled)
    raise unittest.SkipTest('Node unavailable: observer contracts unverified, not RED')


class _ReadbackReplay:
    """Replay actual evaluated JS result through the existing Python outcome gate.

    Navigation/selection are boundary doubles; no new telemetry is injected and
    no claim of trusted real-browser selection is made.
    """
    def __init__(self, result): self.result = result
    def set_default_timeout(self, value): pass
    def add_init_script(self, script): pass
    def goto(self, *args, **kwargs): pass
    def wait_for_function(self, script): pass
    def locator(self, selector): return self
    @property
    def first(self): return self
    def fill(self, value): pass
    def click(self): pass
    def evaluate(self, script):
        if 'gl.readPixels(' in script:
            return copy.deepcopy(self.result)
        if '.requests.filter' in script:
            return 1
        return None


def _motion_observation():
    """Actual probe/decorator, with explicit adapter event doubles.

    Underlying cancellation calls are a harness preflight, not an assertion
    that this fake reproduces browser orbit behavior or animation quality.
    """
    probe, decoration = _observer_scripts()
    source = r'''
const vm=require('node:vm');
let tick=0, frames=[], listeners={}, cancellations=[];
const controls={target:{x:0,y:0,z:0},
  addEventListener(type,callback){(listeners[type]??=[]).push(callback);},
  removeEventListener(){}};
const context={URL,Uint8Array,location:{href:'http://owned.invalid/'},
  performance:{now:()=>tick},
  requestAnimationFrame:callback=>{frames.push(callback);return frames.length;},
  cancelAnimationFrame(){},
  PerformanceObserver:class{observe(){}},
  document:{addEventListener(type,callback){(listeners['document-'+type]??=[]).push(callback);}},
  fetch:async()=>{},
  buildMoodGraphModel(){},renderMap(){},renderDetail(){},renderDetailLoading(){},
  cameraFocusFrame:null,forceGraph:{controls:()=>controls},
  animateCameraFocus(){context.cameraFocusFrame=1;},
  cancelCameraFocus(){cancellations.push(tick);context.cameraFocusFrame=null;},
  setCurrent(){context.cancelCameraFocus();}
};
context.window=context;vm.createContext(context);
// Existing runtime's controls-start cancellation adapter seam.
controls.addEventListener('start',()=>context.cancelCameraFocus());
vm.runInContext(PROBE,context);
vm.runInContext('('+DECORATION+')()',context);
context.__diagnostic.milestones_ms.graph_scene_end=5;
context.__diagnostic.contention_action='armed';
tick=10;context.animateCameraFocus();
tick=20;
for(const callback of listeners['document-input'])callback({type:'input',isTrusted:true});
// Orbit starts while the first motion is owned; latest selection cancels the
// second. Existing boundary calls occurred; observation must not lose them.
tick=30;for(const callback of listeners.start)callback({type:'start'});
tick=40;context.animateCameraFocus();
tick=50;context.setCurrent();
console.log(JSON.stringify({diagnostic:context.__diagnostic,cancellations,
  camera_focus_frame:context.cameraFocusFrame}));
'''
    source = source.replace('PROBE', json.dumps(probe)).replace('DECORATION', json.dumps(decoration))
    completed = subprocess.run([_node(), '-e', source], capture_output=True,
                               text=True, timeout=10)
    if completed.returncode:
        raise AssertionError('Observer harness must execute before RED: ' + completed.stderr)
    return json.loads(completed.stdout)


class BrowserFocusObservationContracts(unittest.TestCase):
    def test_viewport_aspect_fov_and_restrictive_or_unavailable_controls_are_labeled(self):
        cases = (
            ('controls.minDistance=200;controls.maxDistance=250;', 800, 600, 60, 'observed'),
            ('box.width=600;box.height=800;camera.aspect=600/800;camera.fov=75;'
             'context.forceGraph.controls=()=>null;', 600, 800, 75, 'unavailable'),
        )
        for setup, width, height, fov, status in cases:
            with self.subTest(controls=status):
                result = _run_readback(setup)
                if status == 'observed':
                    self.assertEqual(result['controls_before'],
                                     {'min_distance': 200, 'max_distance': 250, 'enabled': True})
                    self.assertEqual(result['controls_after'], result['controls_before'],
                                     'observation must not widen or otherwise mutate actual controls')
                focus = result['sample']['focus']
                self.assertIn('projection', focus,
                              'center-only success omits viewport/FOV and actual controls observation')
                projection = focus['projection']
                self.assertIn('viewport', projection)
                self.assertIn('camera', projection)
                self.assertIn('controls', projection)
                self.assertIn('support_status', projection)
                self.assertIn('usefulness_status', projection)
                self.assertEqual(projection['support_status'], 'unassessed',
                                 'observed aspect/FOV is not an owner-approved supported range')
                self.assertEqual(projection['usefulness_status'], 'unassessed',
                                 'finite geometry and preserved bounds do not prove useful scale')
                self.assertEqual(projection['viewport']['width_px'], width)
                self.assertEqual(projection['viewport']['height_px'], height)
                self.assertEqual(projection['viewport']['aspect'], width / height)
                self.assertEqual(projection['camera']['aspect'], width / height)
                self.assertEqual(projection['camera']['fov_degrees'], fov)
                self.assertEqual(projection['camera']['near'], 1)
                self.assertEqual(projection['camera']['far'], 100)
                observed_controls = projection['controls']
                self.assertEqual(observed_controls['status'], status)
                if status == 'observed':
                    self.assertEqual(observed_controls['min_distance'], 200)
                    self.assertEqual(observed_controls['max_distance'], 250)
                    self.assertIs(observed_controls['restrictive'], True,
                                  'label bounds excluding nominal radius; never silently widen them')
                else:
                    for field in ('min_distance', 'max_distance', 'restrictive'):
                        self.assertIn(field, observed_controls)
                        self.assertIsNone(observed_controls[field], 'unobserved is not permissive')

    def test_wrong_halo_identity_or_unavailable_projection_cannot_report_focus_success(self):
        cases = (
            ('context.selectedNodeHalo.trackId="public-00001";', 'wrong selected halo identity'),
            ('camera.fov=NaN;', 'nonfinite camera projection'),
        )
        for setup, reason in cases:
            with self.subTest(reason=reason):
                raw = _run_readback(setup)['sample']
                self.assertTrue(raw['focus']['selected_node_in_view'],
                                'finite center alone deliberately cannot detect this invalid observation')
                result = diagnostic.observe(_ReadbackReplay(raw), 'http://owned.invalid',
                                            Event(), 'pending-then-ready')
                self.assertEqual(result['outcome'], 'invalid_response', reason)
                self.assertTrue(any(failure['flow'] == 'selection' and
                                    failure['outcome'] == 'invalid_response'
                                    for failure in result['failures']))
                self.assertIsNotNone(result['milestones_ms']['graph_post_focus_readback'],
                                     'retain completed readback when focus observation is invalid')

    def test_active_focus_input_and_orbit_latest_cancellations_survive_observation_and_report(self):
        result = _motion_observation()
        self.assertEqual(result['cancellations'], [30, 50], 'harness reached both existing cancellation seams')
        self.assertIsNone(result['camera_focus_frame'])
        observed = result['diagnostic']
        self.assertEqual(observed['consumed_count'], 2)
        with self.subTest(observation='active-focus-phase'):
            self.assertEqual(observed['input_observations'][0]['phase_at_receipt'], 'focus',
                             'after-scene hides input received during an active focus')
        with self.subTest(observation='cancellation-report'):
            self.assertIn('focus', observed, 'observer must record motion cancellation, not only start count')
            self.assertIn('motion', observed['focus'])
            motion = observed['focus']['motion']
            self.assertIn('cancellations', motion)
            self.assertEqual([(event['reason'], event['at_ms']) for event in motion['cancellations']],
                             [('user-orbit', 30), ('new-selection', 50)])
            self.assertTrue(all(event['clock'] == 'browser-performance'
                                for event in motion['cancellations']))
            report = publish_browser_report(attempts=[{
                **observed, 'profile': 'process-cold', 'outcome': 'timeout', 'elapsed_ms': None,
            }])
            published = report['samples'][0]
            self.assertEqual(published['outcome'], 'timeout', 'cancellation is not invented completion')
            self.assertIn('focus', published, 'retain truthful partial motion through the allowlist boundary')
            self.assertEqual(published['focus']['motion']['cancellations'], motion['cancellations'])
