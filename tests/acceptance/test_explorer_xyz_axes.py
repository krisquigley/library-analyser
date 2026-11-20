"""In-scene axis coordinates and lifecycle: the booted page without a browser, and opt-in Chromium."""
import unittest

from tests.support.explorer_page_harness import ASSETS, PAGE
from tests.support.node_script import run_node_script
from tests.support.explorer_diagnostics_page import GRAPH, SCENE, diagnostics_url, snapshot_is

LABELS = "document.querySelectorAll('.graph-axis-label')"
# The axes as the page shows them: label text and screen placement in the DOM, the axis meshes in the scene (#146).
SHOWN_AXES = """() => {
  const graph = window.explorerDiagnostics.scene().graph, labels = [...document.querySelectorAll('.graph-axis-label')];
  const groups = graph.scene().children.filter(c => c.name === 'mood-xyz-axes');
  return {labels: labels.map(l => l.textContent), screen: labels[0].style.transform, sceneCount: groups.length,
    axes: groups[0].children.map(o => ({name: o.name, position: o.position.toArray()})), nodes: graph.graphData().nodes.length};
}"""

# The axes as the booted page mounts them in the 3D graph's scene, redrawn only when the layout changes (#146).
AXES_LIFECYCLE = r"""
(async () => {
let library = [track('a', 0.2, 0.3, 0.2), track('b', 0.7, 0.5, 0.6)];
routes['/api/state'] = r => r.respond(accepted(null, {epoch: 0}));
routes['/api/mood-axis-graph'] = r => r.respond(graphBody(library));
const axes = () => scene.children.filter(child => child.name === 'mood-xyz-axes');
async function reload(tracks) { library = tracks; await press('reload-graph'); await settle(); }
boot(); await settle();
assert.equal(axes().length, 1, 'one axes group joins the scene');
const group = axes()[0];
assert.deepEqual(group.children.map(mesh => mesh.name), ['axis-x', 'axis-y', 'axis-z']);
for (const mesh of group.children) {
  assert.equal(mesh.raycast(), undefined, 'an axis is never picked as a track');
  assert.ok(Number.isFinite(mesh.position.x) && Number.isFinite(mesh.scale.x), 'each axis is placed and sized');
}
await reload([...library].reverse());
assert.strictEqual(axes()[0], group, 'the same layout keeps the same axes');
await reload([track('a', 0, 0, 0)]);
assert.equal(axes().length, 1, 'a new layout replaces the axes');
assert.notStrictEqual(axes()[0], group);
assert.ok(group.children.every(mesh => mesh.geometry.disposed && mesh.material.disposed), 'the old axes are disposed');
await reload([]);
assert.equal(axes().length, 0, 'no positioned tracks, no axes');
console.log('NODE_SCRIPT_COMPLETED');
})().catch(error => { console.error(error.stack); process.exitCode = 1; });
"""


class GraphAxesTests(unittest.TestCase):
    def test_the_axes_join_the_scene_and_change_only_with_the_layout(self):
        for asset in ASSETS:
            with self.subTest(asset=str(asset)):
                run_node_script(self, PAGE + AXES_LIFECYCLE, str(asset))

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
