"""RED contracts for outward observer telemetry; no responsiveness budgets.

Node runs the real probe and the entrypoint decoration supplied by observe().
The controlled clock measures observer boundaries, not browser/GPU performance.
"""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
from threading import Event
import unittest

from tools import explorer_browser_diagnostic as diagnostic
from tools.explorer_browser_report import publish_browser_report


class _DecorationCaptured(Exception):
    pass


class _CapturePage:
    def set_default_timeout(self, value):
        pass

    def add_init_script(self, script):
        self.probe = script

    def goto(self, *args, **kwargs):
        pass

    def wait_for_function(self, script):
        pass

    def evaluate(self, script):
        self.decoration = script
        raise _DecorationCaptured()


def _observer_scripts():
    page = _CapturePage()
    try:
        diagnostic.observe(page, 'http://owned.invalid', Event(), 'pending-then-ready')
    except _DecorationCaptured:
        pass
    return page.probe, page.decoration


def _run_observer(action):
    """Tiny JS sandbox with one consumed body and explicitly costed operations."""
    node = shutil.which('node') or shutil.which('nodejs')
    if node is None:
        spec = importlib.util.find_spec('playwright')
        if spec and spec.origin:
            bundled = Path(spec.origin).parent / 'driver' / 'node'
            if bundled.is_file():
                node = str(bundled)
    if node is None:
        raise unittest.SkipTest('Node VM unavailable; observer contracts unverified, not RED')
    probe, decoration = _observer_scripts()
    source = r'''
const vm = require('node:vm');
let tick = 0, observer, frames = [], bodyReads = 0;
const graph = {nodes:[{id:'private-node'}],links:[],unpositioned:[]};
const context = {
  URL, Uint8Array, console,
  location:{href:'http://owned.invalid/'},
  performance:{now:()=>tick},
  requestAnimationFrame:callback=>{frames.push(callback);return frames.length;},
  PerformanceObserver:class {
    constructor(callback){observer=callback;}
    observe(){}
  },
  document:{addEventListener(){}},
  JSON:{parse(text){tick+=3;return JSON.parse(text);}},
  TextEncoder:class {encode(text){tick+=5;return new TextEncoder().encode(text);}},
  crypto:{subtle:{async digest(name,bytes){tick+=7;return new Uint8Array(32).buffer;}}},
  fetch:async()=>({ok:true,status:200,headers:{get:()=>null},
    async text(){bodyReads++;tick+=10;return JSON.stringify(graph);}}),
  buildMoodGraphModel(value){tick+=11;return value;},
  renderMap(){tick+=13;},
  renderDetail(){}, renderDetailLoading(){}, setCurrent(){},
  animateCameraFocus(){tick+=17;}
};
context.window=context;
vm.createContext(context);
vm.runInContext(PROBE,context);
vm.runInContext('('+DECORATION+')()',context);
function advanceFrames(time){tick=time;const ready=frames;frames=[];for(const callback of ready)callback(time);}
(async()=>{
  ACTION
  console.log(JSON.stringify({diagnostic:context.__diagnostic,body_reads:bodyReads,tick}));
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
'''
    source = source.replace('PROBE', json.dumps(probe)).replace('DECORATION', json.dumps(decoration))
    source = source.replace('ACTION', action)
    completed = subprocess.run([node, '-e', source], capture_output=True, text=True, timeout=10)
    if completed.returncode != 0:
        raise AssertionError('Observer harness must execute before behavioral RED: ' + completed.stderr)
    return json.loads(completed.stdout)


class BrowserPhaseAttribution(unittest.TestCase):
    def test_observer_verification_and_model_intervals_are_separate(self):
        result = _run_observer('''
const response=await context.fetch('/api/mood-axis-graph');
const value=await response.json();
context.buildMoodGraphModel(value);
context.renderMap();
''')
        self.assertEqual(result['body_reads'], 1, 'do not clone or consume a second body')
        observed = result['diagnostic']['milestones_ms']
        required = ('graph_json_start', 'graph_json_end',
                    'graph_verification_start', 'graph_verification_end',
                    'graph_model_start', 'graph_model_end',
                    'graph_scene_start', 'graph_scene_end')
        self.assertTrue(all(key in observed for key in required),
                        'publish separate parse, UTF8/hash, model and scene start/end timestamps')
        self.assertEqual((observed['graph_json_start'], observed['graph_json_end']), (10, 13))
        self.assertEqual((observed['graph_verification_start'], observed['graph_verification_end']), (13, 25))
        self.assertEqual((observed['graph_model_start'], observed['graph_model_end']), (25, 36))
        self.assertEqual((observed['graph_scene_start'], observed['graph_scene_end']), (36, 49))
        self.assertEqual(result['diagnostic']['graph_response']['consumed_bytes'],
                         len(json.dumps({'nodes': [{'id': 'private-node'}], 'links': [], 'unpositioned': []},
                                        separators=(',', ':')).encode()))

    def test_timestamped_long_task_cross_phase_overlap_remains_ambiguous(self):
        result = _run_observer('''
observer({getEntries:()=>[{startTime:10,duration:60,name:'private attribution /home/user'},
                         {startTime:80,duration:50}]});
''')['diagnostic']
        tasks = result['responsiveness'].get('long_tasks')
        self.assertEqual(tasks, [{'start_ms': 10, 'end_ms': 70, 'duration_ms': 60},
                                 {'start_ms': 80, 'end_ms': 130, 'duration_ms': 50}],
                         'durations alone cannot identify cross-phase overlap')
        # One task intersects model AND scene: overlap is not causal attribution.
        spans = {'model': (25, 36), 'scene': (36, 49)}
        overlaps = {phase: max(0, min(tasks[0]['end_ms'], end) - max(tasks[0]['start_ms'], start))
                    for phase, (start, end) in spans.items()}
        self.assertEqual(overlaps, {'model': 11, 'scene': 13})
        self.assertIn('gpu_time_ms', result['responsiveness'], 'GPU time must be explicitly unavailable')
        self.assertIsNone(result['responsiveness']['gpu_time_ms'], 'main-thread tasks are not GPU timers')
        self.assertNotIn('private attribution', json.dumps(result))

    def test_first_presentation_is_distinct_from_post_focus_readback(self):
        result = _run_observer('''
context.renderMap();
advanceFrames(20);
advanceFrames(30);
context.animateCameraFocus();
advanceFrames(80);
''')['diagnostic']['milestones_ms']
        self.assertIn('graph_first_presentation', result,
                      'record the first scene presentation proxy before waiting for focus/readPixels')
        self.assertGreaterEqual(result['graph_first_presentation'], result['graph_scene_end'])
        self.assertLess(result['graph_first_presentation'], result['focus_start'])
        self.assertIsNone(result.get('graph_post_focus_readback'),
                          'rAF is a presentation proxy, not verified post-focus pixels')
        self.assertNotIn('graph_usable_render', result,
                         'scene submission alone must not manufacture verified usability')

    def test_partial_phase_failures_remain_null_and_publication_redacts(self):
        sample = {'profile': 'process-cold', 'clock': 'browser-performance',
                  'outcome': 'timeout', 'elapsed_ms': None,
                  'milestones_ms': {'graph_json_start': 10, 'graph_json_end': 13,
                                    'graph_verification_start': 13,
                                    'graph_verification_end': float('inf'),
                                    'graph_model_start': float('nan'),
                                    'graph_scene_end': -1,
                                    'private_id': '/home/private/audio.wav'},
                  'responsiveness': {'long_tasks': [
                      {'start_ms': 10, 'end_ms': 70, 'duration_ms': 60,
                       'name': 'private-track', 'path': '/home/private/audio.wav'}],
                      'gpu_time_ms': None, 'private': 'secret'},
                  'private': 'secret'}
        report = publish_browser_report(attempts=[sample], environment={'path': '/home/private'})
        self.assertEqual(len(report['samples']), 1, 'failed attempts remain in the denominator')
        published = report['samples'][0]
        self.assertEqual(published['outcome'], 'timeout')
        phases = published['milestones_ms']
        self.assertEqual(phases.get('graph_json_start'), 10, 'retain completed phase starts')
        self.assertEqual(phases.get('graph_json_end'), 13, 'retain completed phase ends')
        for key in ('graph_verification_end', 'graph_model_start', 'graph_model_end',
                    'graph_scene_start', 'graph_scene_end', 'graph_first_presentation',
                    'graph_post_focus_readback'):
            self.assertIn(key, phases, 'missing/invalid phase values are explicit null, not omitted/zero')
            self.assertIsNone(phases[key])
        self.assertEqual(published.get('responsiveness', {}).get('long_tasks'),
                         [{'start_ms': 10, 'end_ms': 70, 'duration_ms': 60}])
        serialized = json.dumps(report, allow_nan=False)
        for private in ('private-track', '/home/private', 'audio.wav', 'secret', 'private_id'):
            self.assertNotIn(private, serialized)
        self.assertEqual(report['environment'], {})


if __name__ == '__main__':
    unittest.main()
