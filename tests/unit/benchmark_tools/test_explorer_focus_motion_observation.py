"""Outward cancellation chronology, not a smooth-motion or latency gate."""
import json
import subprocess
import unittest

from tests.acceptance.test_explorer_browser_focus_usefulness import _node
from tests.unit.benchmark_tools.test_explorer_browser_phase_attribution import _observer_scripts


def motion_case(actions):
    probe, decoration = _observer_scripts()
    source = r'''
const vm=require('node:vm');let tick=0, listeners={},frames=[];
const controls={addEventListener(type,cb){(listeners[type]??=[]).push(cb);}};
const c={URL,location:{href:'http://owned.invalid/'},performance:{now:()=>tick},
requestAnimationFrame:cb=>frames.push(cb),PerformanceObserver:class{observe(){}},
document:{addEventListener(type,cb){(listeners['doc-'+type]??=[]).push(cb);}},fetch:async()=>{},
buildMoodGraphModel(){},renderMap(){},renderDetail(){},renderDetailLoading(){},
cameraFocusFrame:null,forceGraph:{controls:()=>controls},
setCurrent(){c.cancelCameraFocus();},cancelCameraFocus(){c.cameraFocusFrame=null;},
animateCameraFocus(){c.cancelCameraFocus();c.cameraFocusFrame=1;}};
c.window=c;vm.createContext(c);vm.runInContext(PROBE,c);vm.runInContext('('+DECORATION+')()',c);
c.__diagnostic.milestones_ms.graph_scene_end=1;c.__diagnostic.contention_action='armed';
ACTIONS
console.log(JSON.stringify(c.__diagnostic));
'''.replace('PROBE', json.dumps(probe)).replace('DECORATION', json.dumps(decoration)).replace('ACTIONS', actions)
    result = subprocess.run([_node(), '-e', source], capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


class FocusMotionObservationTests(unittest.TestCase):
    def test_starts_retain_chronology_without_invented_completion(self):
        observed = motion_case('tick=10;c.animateCameraFocus();tick=20;c.setCurrent();'
                               'tick=30;c.animateCameraFocus();')
        motion = observed['focus']['motion']
        self.assertIn('starts', motion)
        self.assertEqual(motion['starts'], [
            {'at_ms': 10, 'clock': 'browser-performance', 'active_after': True},
            {'at_ms': 30, 'clock': 'browser-performance', 'active_after': True}])
        self.assertNotIn('completion', motion)

    def test_canvas_pointer_receipt_retains_trust_and_active_focus(self):
        observed = motion_case('c.forceGraph.renderer=()=>({domElement:canvas});const canvas={};'
                               'tick=10;c.animateCameraFocus();tick=20;'
                               "for(const cb of listeners['doc-pointerdown']||[])cb({type:'pointerdown',isTrusted:true,target:canvas});")
        self.assertEqual(len(observed['input_observations']), 1)
        record = observed['input_observations'][0]
        self.assertEqual(record['action'], 'orbit')
        self.assertEqual(record['phase_at_receipt'], 'focus')
        self.assertIs(record['is_trusted'], True)

    def test_direct_controls_start_callback_labels_actual_cancellation(self):
        observed = motion_case("controls.addEventListener('start',c.cancelCameraFocus);"
                               "tick=10;c.animateCameraFocus();tick=20;"
                               "for(const cb of listeners.start)cb({type:'start'});")
        self.assertEqual(observed['focus']['motion']['cancellations'], [
            {'reason': 'user-orbit', 'at_ms': 20, 'clock': 'browser-performance'}])

    def test_idle_selection_does_not_invent_cancellation(self):
        observed = motion_case('tick=10;c.setCurrent();')
        self.assertIn('focus', observed)
        self.assertEqual(observed['focus']['motion']['cancellations'], [])

    def test_completion_does_not_leave_input_in_focus_phase(self):
        observed = motion_case('tick=10;c.animateCameraFocus();c.cameraFocusFrame=null;tick=20;'
                               "listeners['doc-input'][0]({type:'input',isTrusted:true});")
        self.assertEqual(observed['input_observations'][0]['phase_at_receipt'], 'after-scene')

    def test_unclassified_cancellation_is_not_invented_as_orbit(self):
        observed = motion_case('tick=10;c.animateCameraFocus();tick=20;c.cancelCameraFocus();')
        self.assertIn('focus', observed)
        self.assertEqual(observed['focus']['motion']['cancellations'], [
            {'reason': 'unclassified', 'at_ms': 20, 'clock': 'browser-performance'}])

    def test_superseding_focus_is_distinguished_from_new_selection(self):
        observed = motion_case('tick=10;c.animateCameraFocus();tick=20;c.animateCameraFocus();')
        self.assertIn('focus', observed)
        self.assertEqual(observed['focus']['motion']['cancellations'], [
            {'reason': 'new-focus', 'at_ms': 20, 'clock': 'browser-performance'}])
