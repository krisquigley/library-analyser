"""Small orchestration contracts; supplied fakes are NOT real-browser evidence.

No Chromium is launched here. These tests require the host to attempt trusted
Playwright input after release AND an active body-consumption signal, before
waiting for graph-ready/focus completion.
They do not pretend a synchronous page callback can run during blocking JS.
Receipt and next-frame observations belong to the page's performance clock;
host dispatch intent remains separately labeled even if the page never replies.
The fake signals body start with body end absent, never concurrent JS callbacks.
A later coordinated, bounded real browser gate must demonstrate actual overlap
with body/model/scene spans. This module asserts no performance/GPU budget.
"""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from tools import explorer_browser_diagnostic as tool


def _active_body_predicate(script):
    """Evaluate the actual wait predicate against inflight and completed bodies."""
    node = shutil.which('node') or shutil.which('nodejs')
    if node is None:
        spec = importlib.util.find_spec('playwright')
        if spec and spec.origin:
            bundled = Path(spec.origin).parent / 'driver' / 'node'
            if bundled.is_file():
                node = str(bundled)
    if node is None:
        raise unittest.SkipTest('Node VM unavailable; active phase gate unverified, not RED')
    source = r'''
const vm=require('node:vm'), predicate=JSON.parse(process.argv[1]);
const values=[null,120].map(end=>{
  const milestones_ms={graph_body_start:100,graph_body_end:end};
  const context={window:{__diagnostic:{milestones_ms}},
                 graphLoadState:{status:end===null?'loading':'ready'}};
  context.__diagnostic=context.window.__diagnostic;
  vm.createContext(context);
  const value=vm.runInContext('('+predicate+')',context);
  return Boolean(typeof value==='function'?value():value);
});
process.stdout.write(JSON.stringify(values));
'''
    result = subprocess.run([node, '-e', source, json.dumps(script)],
                            capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise AssertionError('Active phase predicate must execute: ' + result.stderr)
    return json.loads(result.stdout)


class TimeoutError(Exception):
    pass


class Release:
    def __init__(self, log):
        self.log = log
        self.released = False

    def set(self):
        self.released = True
        self.log.append('graph-release')


class ControlledPage:
    """Protocol fake recording host actions, not executing fabricated browser JS.

    The final response contains supplied receipt/frame observations in a clock
    intentionally unrelated to host monotonic time. They are not measured input
    latency and cannot establish that an attempt occurred under contention.
    """
    def __init__(self, release, *, timeout=False):
        self.release = release
        self.log = release.log
        self.timeout = timeout
        self.row = 0
        self.selector = None
        self.active_phase = None
        self.body_start = None
        self.body_end = None
        self.result = {
            'milestones_ms': {'graph_usable_render': 220}, 'requests': [],
            'render': {'canvas_visible': True, 'nonempty_pixels': True,
                       'positioned_nodes_visible': True},
            'focus': {'selected_node_in_view': True, 'halo_visible': True,
                      'finite_camera': True, 'consumed_count': 1,
                      'projection': {'status': 'observed',
                                     'mesh': {'diameter_px': 10, 'diameter_viewport_fraction': .1},
                                     'halo': {'diameter_px': 20, 'diameter_viewport_fraction': .2}}},
            'selection': {'accepted': True, 'latest_accepted': True},
            'input_observations': [{
                'receipt_clock': 'browser-performance', 'received_ms': 170,
                'frame_ms': 190, 'is_trusted': True,
                # Receipt after model/scene is allowed; attempted input may wait
                # behind synchronous work. No assertion of responsiveness.
                'phase_at_receipt': 'after-scene'}]}

    def on(self, event, handler): pass
    def set_default_timeout(self, timeout): pass
    def add_init_script(self, script): pass
    def goto(self, *args, **kwargs): pass

    def wait_for_function(self, script):
        # Model a response body that has started but has not completed. This is
        # a protocol signal, NOT execution of JS concurrently with a long task.
        if 'graph_body_start' in script and 'graph_body_end' in script:
            if not self.release.released:
                raise AssertionError('body consumption cannot start while graph is held')
            if _active_body_predicate(script) != [True, False]:
                raise AssertionError('body gate must accept inflight and reject completed consumption')
            self.body_start = 100
            self.body_end = None
            self.active_phase = 'body'
            self.log.append('body-consumption-active')
        if "graphLoadState.status==='ready'" in script:
            self.log.append('wait-graph-ready')

    def locator(self, selector):
        self.selector = selector
        return self

    def get_by_role(self, *args, **kwargs): return self
    def is_visible(self): return True
    @property
    def first(self):
        self.row = 0
        return self

    def nth(self, index):
        self.row = index
        return self

    def fill(self, text):
        self.log.append('trusted-input-api')
        if self.timeout and self.release.released:
            raise TimeoutError('private input timeout')

    def click(self):
        self.log.append('trusted-selection-api')
        if self.timeout and self.release.released:
            raise TimeoutError('private selection timeout')

    def evaluate(self, script):
        # A dispatchEvent or DOM .click() cannot establish trusted input.
        if 'dispatchEvent(' in script or '.click()' in script:
            self.log.append('untrusted-page-dispatch')
        if self.timeout and self.release.released:
            # Browser recovery may be impossible. Host intent must survive.
            raise TimeoutError('private page unresponsive')
        if 'const d=window.__diagnostic, renderer=' in script:
            return copy.deepcopy(self.result)
        if '.requests.filter' in script:
            return 0
        return None


class BrowserContentionOrchestrationContracts(unittest.TestCase):
    def setUp(self):
        # Preflight outside observe_attempt: its failure retention catches
        # exceptions, which must not convert a missing Node SkipTest into RED.
        self.assertEqual(_active_body_predicate('true'), [True, True])

    def test_graph_release_precedes_superseding_input_and_records_receipt_frame(self):
        log = []
        release = Release(log)
        sample = tool.observe_attempt(ControlledPage(release), 'http://127.0.0.1/',
                                      release, 'during-consumption')
        self.assertEqual(sample['outcome'], 'ok')
        start = log.index('graph-release')
        finish = log.index('wait-graph-ready')
        actions = log[start + 1:finish]
        self.assertIn('body-consumption-active', actions,
                      'release alone is not evidence that consumption actually started')
        signal = actions.index('body-consumption-active')
        self.assertIn('trusted-input-api', actions,
                      'attempt must follow release BEFORE waiting for ready; pending-network input is not contention')
        self.assertIn('trusted-selection-api', actions,
                      'superseding selection must be attempted during consumption, not only while held pending')
        self.assertLess(signal, actions.index('trusted-input-api'))
        self.assertLess(signal, actions.index('trusted-selection-api'))
        self.assertNotIn('untrusted-page-dispatch', log)
        observations = sample.get('input_observations', [])
        self.assertTrue(observations, 'retain attempted input and page receipt observations')
        record = observations[-1]
        self.assertEqual(record.get('phase_at_attempt'), 'body',
                         'record actual active consumption phase, not graph-released')
        self.assertEqual(record.get('attempt_clock'), 'host-monotonic')
        self.assertIsInstance(record.get('attempt_ms'), (int, float))
        self.assertEqual(record['receipt_clock'], 'browser-performance')
        self.assertTrue(record['is_trusted'])
        self.assertLessEqual(record['received_ms'], record['frame_ms'])
        self.assertNotIn('attempt_to_receipt_ms', record,
                         'unrelated host/browser clocks cannot be subtracted without calibration')

    def test_contention_timeout_retains_attempt_not_success(self):
        log = []
        release = Release(log)
        sample = tool.observe_attempt(ControlledPage(release, timeout=True),
                                      'http://127.0.0.1/', release, 'during-consumption')
        self.assertEqual(sample['outcome'], 'timeout')
        self.assertIn('body-consumption-active', log, 'timeout must occur after active consumption was observed')
        self.assertIn('trusted-input-api', log[log.index('body-consumption-active') + 1:],
                      'exercise timeout of a host input attempt, not just final readback')
        records = sample.get('input_observations', [])
        self.assertTrue(records, 'host intent must survive timeout even when page recovery fails')
        record = records[-1]
        self.assertEqual(record.get('phase_at_attempt'), 'body',
                         'record actual active consumption phase, not graph-released')
        self.assertEqual(record.get('attempt_clock'), 'host-monotonic')
        self.assertIsInstance(record.get('attempt_ms'), (int, float))
        for key in ('received_ms', 'frame_ms', 'is_trusted'):
            self.assertIn(key, record, 'unknown receipt/frame is explicit null, not success')
            self.assertIsNone(record[key])
        self.assertEqual(record.get('outcome'), 'timeout')
        self.assertNotIn('private', str(sample))
        self.assertIsNone(sample['elapsed_ms'])


if __name__ == '__main__':
    unittest.main()
