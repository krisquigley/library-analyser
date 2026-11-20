"""In-scene axis coordinates and lifecycle, without a browser or audio database."""
import shutil
import subprocess
import unittest
from pathlib import Path

from tests.support.explorer_app_bundle import explorer_app_script
from tests.support.explorer_diagnostics_page import GRAPH, SCENE, diagnostics_url, snapshot_is

LABELS = "document.querySelectorAll('.graph-axis-label')"
# The axes as the page shows them: label text and screen placement in the DOM, the axis meshes in the scene (#146).
SHOWN_AXES = """() => {
  const graph = window.explorerDiagnostics.scene().graph, labels = [...document.querySelectorAll('.graph-axis-label')];
  const groups = graph.scene().children.filter(c => c.name === 'mood-xyz-axes');
  return {labels: labels.map(l => l.textContent), screen: labels[0].style.transform, sceneCount: groups.length,
    axes: groups[0].children.map(o => ({name: o.name, position: o.position.toArray()})), nodes: graph.graphData().nodes.length};
}"""

APP_JS = explorer_app_script(Path(__file__).resolve().parents[2] / 'music_analyzer/frameworks/explorer/assets/app.js')


class GraphAxesTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node required for browser model tests')
    def test_axis_spec_and_scene_lifecycle(self):
        script = r'''
const assert=require('assert');
const {graphAxisSpec, syncGraphAxes}=require(process.argv[1]);
const nodes=[{x:72,y:108,z:4320},{x:252,y:180,z:4608}];
const spec=graphAxisSpec(nodes);
assert.deepStrictEqual(spec.map(a=>a.label),['X valence (native)','Y arousal (native)','Z BPM']);
assert.deepStrictEqual(spec.map(a=>a.end[a.key]-a.start[a.key]),[216,108,324]);
assert.deepStrictEqual(spec.map(a=>a.references),[['0.2','0.7'],['0.3','0.5'],['120.0','128.0']]);
assert.deepStrictEqual(graphAxisSpec([...nodes].reverse()),spec);
assert.deepStrictEqual(graphAxisSpec([]),[]);
class Sphere {constructor(radius){this.radius=radius} dispose(){this.disposed=true}}
class Material {constructor(props){this.props=props} dispose(){this.disposed=true}}
class Mesh {constructor(geometry,material){this.geometry=geometry;this.material=material;this.position={set:(...v)=>this.xyz=v};this.scale={set:(...v)=>this.wh=v};this.rotation={set:(...v)=>this.angles=v}}}
class Scene {constructor(){this.children=[]} add(o){this.children.push(o);o.parent=this} remove(o){this.children.splice(this.children.indexOf(o),1)}}
const scene=new Scene();
const nodeMesh=new Mesh(new Sphere(4),new Material({})); nodeMesh.__graphObjType="node"; scene.children.push({children:[nodeMesh]});
const graph={scene:()=>scene,graphData:()=>({nodes:[{__threeObj:new Mesh(new Sphere(4),new Material({}))}]})};
let group=syncGraphAxes(graph,spec);
assert.equal(scene.children.length,2);assert.equal(group.children.length,3);
assert(group.children.every(c=>c.raycast && c.xyz && c.wh));
assert.strictEqual(syncGraphAxes(graph,graphAxisSpec([...nodes].reverse())),group);
assert.equal(scene.children.length,2);
syncGraphAxes(graph,graphAxisSpec([{x:0,y:0,z:0}]));
assert.equal(scene.children.length,2);
assert(group.children.every(c=>c.geometry.disposed && c.material.disposed));
syncGraphAxes(graph,[]);
assert.equal(scene.children.length,1);
'''
        result = subprocess.run(['node', '-e', script, str(APP_JS)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

@unittest.skipUnless(__import__('os').environ.get('RUN_BROWSER_SMOKE') == '1', 'opt-in Chromium')
class GraphAxesBrowserTests(unittest.TestCase):
    def test_orbit_mood_change_and_node_picking(self):
        import tempfile
        import threading
        from pathlib import Path
        from playwright.sync_api import sync_playwright
        from tests.support.three_track_graph_db import create_three_track_graph_db
        from music_analyzer.frameworks.explorer.server import create_server

        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / 'synthetic.sqlite'
            ids = create_three_track_graph_db(db)
            server = create_server(str(db), port=0)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(executable_path='/usr/bin/chromium', args=['--use-gl=angle', '--use-angle=swiftshader', '--enable-webgl'])
                    page = browser.new_page(viewport={'width': 1280, 'height': 900})
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(diagnostics_url(f'http://127.0.0.1:{server.server_port}/'))
                    page.wait_for_function(f"{LABELS}.length === 6 && !!{SCENE}.graph")
                    before = page.evaluate(SHOWN_AXES)
                    self.assertEqual(before['nodes'], 2)
                    self.assertEqual(before['sceneCount'], 1)
                    self.assertEqual(before['labels'][::2], ['X valence (native)', 'Y arousal (native)', 'Z BPM'])
                    page.evaluate(f'() => {{{SCENE}.graph.cameraPosition({{x:900,y:1200,z:4300}},{{x:100,y:60,z:4450}},0);return true}}')
                    page.wait_for_function(f'{LABELS}[0].style.transform !== ' + repr(before['screen']))
                    page.locator('#selected-mood').select_option('relaxing')
                    page.wait_for_function(f"{GRAPH}.model.selectedMood === 'relaxing'")
                    after = page.evaluate(SHOWN_AXES)
                    self.assertEqual(after['axes'], before['axes'])
                    self.assertEqual(after['sceneCount'], 1)
                    self.assertEqual(after['nodes'], 2)
                    self.assertNotEqual(after['screen'], before['screen'])
                    # Click the actual rendered node screen coordinate; axis meshes must not intercept.
                    page.evaluate(f'() => {{const g={SCENE}.graph, n=g.graphData().nodes[0];'
                                  'g.cameraPosition({x:n.x,y:n.y,z:n.z+500},{x:n.x,y:n.y,z:n.z},0);return true}')
                    page.wait_for_timeout(500)
                    point = page.evaluate(f'() => {{const g={SCENE}.graph, n=g.graphData().nodes[0];'
                                          'return g.graph2ScreenCoords(n.x,n.y,n.z)}')
                    page.evaluate('document.querySelectorAll("details").forEach(d=>d.open=false)')
                    page.mouse.move(point['x'],point['y'])
                    page.wait_for_timeout(250)
                    page.mouse.click(point['x'], point['y'])
                    page.wait_for_function(snapshot_is('(s.currentTrackId||"") === ' + repr(ids[0])), timeout=4000)
                    self.assertFalse(errors, errors)
                    browser.close()
            finally:
                server.shutdown()
                server.server_close()
