"""The Explorer page composed (#146): the real page, booted as in a browser, driven as the listener and server
would, and observed only through its diagnostics seam, its DOM, its requests and the 3D graph's boundary."""
import unittest

from tests.support.explorer_page_harness import ASSETS, PAGE
from tests.support.node_script import run_node_script

LIBRARY = r'''
const library = [track('a'), track('b', -0.7, 0.8, 0.2)];
routes['/api/state'] = r => r.respond(accepted(null, {epoch: 0}));
routes['/api/mood-axis-graph'] = r => r.respond(graphBody(library));
routes['/api/tracks/summary'] = r => r.respond(summaryBody(library.filter(t => t.id === r.url.searchParams.get('query'))));
routes['/api/tracks/<id>'] = r => r.respond(detailBody(r.path.split('/').pop()));
const seam = boot();
const heard = [];
for (const type of seam.eventTypes()) seam.subscribe(type, event => heard.push(event.type));
'''


def scenario(body):
    return PAGE + '(async () => {\n' + LIBRARY + body + "\nconsole.log('NODE_SCRIPT_COMPLETED');\n})()" \
        ".catch(error => { console.error(error.stack); process.exitCode = 1; });"


class ExplorerPageCompositionTests(unittest.TestCase):
    def run_scenario(self, body):
        for asset in ASSETS:
            with self.subTest(asset=str(asset)):
                run_node_script(self, scenario(body), str(asset))

    def test_startup_loads_the_graph_and_the_listeners_state_without_being_asked(self):
        self.run_scenario(r'''
await settle(6);
assert.deepEqual(requests.map(r => r.path), ['/api/mood-axis-graph', '/api/state']);
assert.equal(requests[0].url.searchParams.get('contract'), 'v3');
assert.deepEqual(mounted.nodes.map(n => n.id), ['a', 'b']);
const now = seam.snapshot();
assert.deepEqual([now.graphStatus, now.currentTrackId, now.selectionEpoch], ['ready', null, 0]);
assert.ok(heard.includes('graph-ready') && heard.includes('no-track-selected'), heard.join(' '));
''')

    def test_a_track_chosen_from_search_is_accepted_shown_and_focused(self):
        self.run_scenario(r'''
routes['/api/current'] = r => r.respond(accepted(r.body.track_id));
await settle(6);
await search('b'); await settle(2);
assert.deepEqual(rows().map(r => r.dataset.trackId), ['b']);
heard.length = 0;
await chooseRow('b'); await settle(4); await untilCameraSettles();
assert.ok(heard.includes('camera-focus-finished'), heard.join(' '));
const {track_id, selection_epoch} = request('/api/current').body;
assert.deepEqual({track_id, selection_epoch}, {track_id: 'b', selection_epoch: 0});
assert.equal(seam.snapshot().currentTrackId, 'b');
for (const type of ['track-chosen', 'selection-accepted', 'track-detail-loaded', 'camera-focus-started'])
  assert.ok(heard.includes(type), type + ' in ' + heard.join(' '));
assert.ok(byId('detail').innerText.includes('Track b'), 'the accepted track is shown');
const halo = scene.children.find(child => child.userData?.role === 'selected-node-halo');
assert.equal(halo?.userData.trackId, 'b', 'the halo marks the chosen track');
const node = mounted.nodes.find(n => n.id === 'b');
assert.deepEqual(cameraMoves.at(-1).target, {x: node.fx, y: node.fy, z: node.fz}, 'the camera ends looking at it');
''')


if __name__ == '__main__':
    unittest.main()
