"""Outward cancellation chronology, not a smooth-motion or latency gate.

The probe hears the page's camera events through the diagnostics seam (#146); a cancellation's reason is the
cause the page put on its event, so neither listener order nor clock ticks can change it.
"""
import json
import subprocess
import unittest

from tests.acceptance.test_explorer_browser_focus_usefulness import _node
from tests.support.fake_explorer_diagnostics import FAKE_EXPLORER_DIAGNOSTICS
from tests.unit.benchmark_tools.test_explorer_browser_phase_attribution import _observer_scripts


def motion_case(actions):
    """Run the real probe and decoration against a page that focuses, cancels and selects through its events."""
    probe, decoration = _observer_scripts()
    source = FAKE_EXPLORER_DIAGNOSTICS + r'''
const vm=require('node:vm');let tick=0, listeners={},frames=[];
const page={active:false,canvas:null};
const seam=fakeExplorerDiagnostics({snapshot:()=>({cameraFocusActive:page.active}),
  scene:()=>({graph:{renderer:()=>({domElement:page.canvas})}})});
const c={URL,location:{href:'http://owned.invalid/'},performance:{now:()=>tick},
requestAnimationFrame:cb=>frames.push(cb),PerformanceObserver:class{observe(){}},
document:{addEventListener(type,cb){(listeners['doc-'+type]??=[]).push(cb);}},fetch:async()=>{},
explorerDiagnostics:seam};
// As the page does: an arc in flight is cancelled with its cause; a new arc is in flight once it starts.
function cancel(cause){if(!page.active)return;page.active=false;seam.publish({type:'camera-focus-cancelled',frame:1,cause});}
function focus(){cancel('new-focus');seam.publish({type:'camera-focus-started',focusGeneration:tick});page.active=true;}
function finish(){page.active=false;seam.publish({type:'camera-focus-finished'});}
c.window=c;vm.createContext(c);vm.runInContext(PROBE,c);vm.runInContext('('+DECORATION+')()',c);
c.__diagnostic.milestones_ms.graph_scene_end=1;c.__diagnostic.contention_action='armed';
(async()=>{
ACTIONS
await null;await null;console.log(JSON.stringify(c.__diagnostic));
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
'''.replace('PROBE', json.dumps(probe)).replace('DECORATION', json.dumps(decoration)).replace('ACTIONS', actions)
    result = subprocess.run([_node(), '-e', source], capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


def cancellation(reason, at_ms):
    return {'reason': reason, 'at_ms': at_ms, 'clock': 'browser-performance'}


class FocusMotionObservationTests(unittest.TestCase):
    def test_each_cause_the_page_gives_is_reported_as_its_reason(self):
        for cause, reason in (('listener-orbit', 'user-orbit'), ('new-selection', 'new-selection'),
                              ('new-focus', 'new-focus'), ('graph-filtered', 'unclassified'),
                              ('camera-failure', 'unclassified')):
            with self.subTest(cause=cause):
                observed = motion_case(f"tick=10;focus();tick=20;cancel('{cause}');")
                self.assertEqual(observed['focus']['motion']['cancellations'], [cancellation(reason, 20)])

    def test_a_superseding_focus_is_distinguished_from_a_new_selection(self):
        observed = motion_case("tick=10;focus();tick=20;focus();tick=30;cancel('new-selection');")
        self.assertEqual(observed['focus']['motion']['cancellations'],
                         [cancellation('new-focus', 20), cancellation('new-selection', 30)])

    def test_an_idle_selection_does_not_invent_a_cancellation(self):
        observed = motion_case("tick=10;cancel('new-selection');")
        self.assertEqual(observed['focus']['motion'], {'starts': [], 'cancellations': []})

    def test_starts_retain_chronology_without_invented_completion(self):
        observed = motion_case("tick=10;focus();await null;tick=20;cancel('new-selection');"
                               'tick=30;focus();')
        motion = observed['focus']['motion']
        self.assertEqual(motion['starts'], [
            {'at_ms': 10, 'clock': 'browser-performance', 'active_after': True},
            {'at_ms': 30, 'clock': 'browser-performance', 'active_after': True}])
        self.assertNotIn('completion', motion)

    def test_a_start_whose_arc_never_runs_is_not_active_after(self):
        observed = motion_case("tick=10;focus();cancel('graph-reloaded');")
        self.assertEqual(observed['focus']['motion']['starts'], [
            {'at_ms': 10, 'clock': 'browser-performance', 'active_after': False}])

    def test_canvas_pointer_receipt_retains_trust_and_active_focus(self):
        observed = motion_case("page.canvas={};tick=10;focus();tick=20;"
                               "for(const cb of listeners['doc-pointerdown']||[])"
                               "cb({type:'pointerdown',isTrusted:true,target:page.canvas});")
        self.assertEqual(len(observed['input_observations']), 1)
        record = observed['input_observations'][0]
        self.assertEqual(record['action'], 'orbit')
        self.assertEqual(record['phase_at_receipt'], 'focus')
        self.assertIs(record['is_trusted'], True)

    def test_completion_does_not_leave_input_in_focus_phase(self):
        observed = motion_case("tick=10;focus();finish();tick=20;"
                               "listeners['doc-input'][0]({type:'input',isTrusted:true});")
        self.assertEqual(observed['input_observations'][0]['phase_at_receipt'], 'after-scene')


if __name__ == '__main__':
    unittest.main()
