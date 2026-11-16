"""Explorer graph renders on demand instead of redrawing every frame.

The bundled 3d-force-graph loop redraws WebGL on every animation frame even
when nothing in the view changes. Under software rendering that continuous
redraw starves the page's main thread (#86: a trivial in-page fetch took
~120 ms with a 1,000-node graph on screen versus ~0.7 ms with it hidden).

These scenarios run the real packaged app.js against the fake ForceGraph
boundary and observe only the public vendor animation API.
"""
import shutil
import subprocess
import unittest

from tests.acceptance.test_explorer_selection_camera_integration import (
    ASSETS, FIXTURE, ROOT, replace_fixture_seam)

VENDOR_LOOP = '''
  if(key==='pauseAnimation') return ()=>{loop.push('pause'); loop.running=false; return graph;};
  if(key==='resumeAnimation') return ()=>{loop.push('resume'); loop.running=true; return graph;};
  if(key==='onNodeClick')'''

ELEMENT_EVENTS = ('getBoundingClientRect() {return {width:800,height:600,left:0,top:0};}\n'
                  '  addEventListener(type,fn) {(this.listeners[type] ||= []).push(fn);}\n'
                  '  dispatch(type) {for(const fn of this.listeners[type]||[]) fn({type});}')


def fixture():
    text = replace_fixture_seam(FIXTURE, "\n  if(key==='onNodeClick')", VENDOR_LOOP)
    text = replace_fixture_seam(text, 'this.clientWidth=800; this.clientHeight=600; }',
                                'this.clientWidth=800; this.clientHeight=600; this.listeners={}; }')
    text = replace_fixture_seam(text, 'getBoundingClientRect() {return {width:800,height:600,left:0,top:0};}',
                                ELEMENT_EVENTS)
    return text.replace('const frames = [],', 'const loop=Object.assign([],{running:true});\nconst frames = [],', 1)


# Advance in small real-time steps so idleness is measured, not one 700 ms jump.
HELPERS = r'''
function frame(ms=16) {fixtureClock+=ms; const pending=frames.splice(0); for(const callback of pending) callback(fixtureClock);}
function idle(ms=2000) {for(let t=0;t<ms;t+=16) frame();}
'''


class GraphRenderOnDemandTests(unittest.TestCase):
    def run_scenario(self, scenario):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Node required: RED must not be accepted via skipped tests')
        for asset in ASSETS:
            with self.subTest(asset=str(asset.relative_to(ROOT))):
                script = (fixture() + HELPERS + scenario +
                          '\n})().then(()=>console.log("SCENARIO_COMPLETED")).catch(error=>{console.error(error);process.exitCode=1;});')
                result = subprocess.run([node, '-e', script, str(asset)], cwd=ROOT,
                                        capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('SCENARIO_COMPLETED', result.stdout,
                              'Node exited before the async scenario completed: ' + result.stderr)

    def test_still_graph_stops_redrawing(self):
        self.run_scenario(r'''
render(); idle();
assert.equal(loop.running,false,'a still view must not keep redrawing every frame');
assert.deepEqual([...loop],['pause'],'paused once, through the public vendor API');
''')

    def test_changed_camera_pose_resumes_redrawing(self):
        self.run_scenario(r'''
render(); idle(); loop.length=0;
// Programmatic pose changes (tests, tools, vendor helpers) bypass input events.
graph.cameraPosition({x:1,y:2,z:3},{x:0,y:0,z:0},0); frame();
assert.equal(loop.running,true,'a moved camera must be redrawn');
idle();
assert.deepEqual([...loop],['resume','pause'],'and settles again once still');
''')

    def test_pointer_input_resumes_redrawing_for_controls_and_hover(self):
        self.run_scenario(r'''
render(); idle();
for(const type of ['pointerdown','pointermove','wheel']) {
  loop.length=0;
  elements.graph3d.dispatch(type);
  assert.equal(loop.running,false,type+' must not draw inside the input handler');
  frame();
  assert.equal(loop.running,true,type+' must redraw: controls and hover update only in the vendor loop');
  idle();
  assert.deepEqual([...loop],['resume','pause'],type+' wake settles again');
}
''')

    def test_graph_data_or_selection_change_resumes_redrawing(self):
        self.run_scenario(r'''
render(); idle(); loop.length=0;
// Same layout, so no reframing moves the camera: only the data changed.
const linked=model(); linked.links=[{source:'a',target:'b',score:0.5}];
render(linked); frame(); assert.equal(loop.running,true,'new graph data is redrawn');
idle(); loop.length=0;
await select('b'); frame();
assert.equal(loop.running,true,'a selection (node size, halo, focus) is redrawn');
idle(); assert.equal(loop.running,false);
''')

    def test_camera_focus_motion_keeps_redrawing_until_it_ends(self):
        self.run_scenario(r'''
render(); idle(); await select('a'); frame();
for(let t=0;t<600;t+=16) {frame(); assert.equal(loop.running,true,'focus motion is visible throughout');}
idle(); assert.equal(loop.running,false,'and the settled pose stops redrawing');
''')

    def test_resize_resumes_redrawing(self):
        self.run_scenario(r'''
render(); idle(); loop.length=0;
for(const callback of resizeCallbacks) callback();
frame(); assert.equal(loop.running,true,'a resized canvas is redrawn');
''')


if __name__ == '__main__':
    unittest.main()
