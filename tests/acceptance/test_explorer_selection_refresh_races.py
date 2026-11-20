"""A selection and a library refresh racing each other (#146): the real page, booted as in a browser, driven as the
listener and the server would, and observed through its diagnostics seam, its DOM, its requests and the 3D graph's
boundary. The server's authoritative selection always wins, and a stale response never repaints the page."""
import unittest

from tests.support.explorer_page_harness import ASSETS, PAGE
from tests.support.node_script import run_node_script

LIBRARY = r'''
const library = [track('a'), track('b', -0.7, 0.8, 0.2)];
const listed = () => rows().map(item => item.dataset.trackId);
const currentRows = () => rows().filter(item => item.className === 'current').map(item => item.dataset.trackId);
const detailText = () => walk(byId('detail')).map(node => node.ownText || '').join(' ');
const asked = path => requests.filter(item => item.path === path).length;
'''


def scenario(body):
    return PAGE + '(async () => {\n' + LIBRARY + body + "\nconsole.log('NODE_SCRIPT_COMPLETED');\n})()" \
        ".catch(error => { console.error(error.stack); process.exitCode = 1; });"


class SelectionRefreshRaceTests(unittest.TestCase):
    def run_scenario(self, body):
        for asset in ASSETS:
            with self.subTest(asset=str(asset)):
                run_node_script(self, scenario(body), str(asset))

    def test_refresh_after_a_rejected_selection_keeps_the_servers_selection(self):
        self.run_scenario(r'''
routes['/api/state'] = r => r.respond(accepted('b', {epoch: 2}));
routes['/api/tracks/summary'] = r => r.respond(summaryBody(library));
routes['/api/tracks/<id>'] = r => r.respond(detailBody(r.path.split('/').pop()));
routes['/api/current'] = r => r.respond({...accepted('b', {epoch: 2}), selection_accepted: false});
const seam = boot(); await settle(); await search('Track'); await settle();
assert.deepEqual(listed(), ['a', 'b'], 'the search lists both tracks');
await chooseRow('a'); await settle();
assert.equal(seam.snapshot().currentTrackId, 'b', 'a rejected choice restores the server selection');
const before = requests.length;
await press('loading-retry'); await settle();
assert.equal(seam.snapshot().currentTrackId, 'b', 'a refresh after the rejection does not revive the rejected choice');
assert.deepEqual(currentRows(), ['b']);
assert.match(detailText(), /Track b/, 'detail follows the server selection');
const refreshed = requests.slice(before).map(item => item.path);
assert.ok(refreshed.includes('/api/state'), 'the refresh read the library state');
assert.ok(!refreshed.includes('/api/tracks/summary'), 'the refresh keeps the search rows');
assert.ok(!requests.some(item => item.path.startsWith('/api/candidates')), 'no candidate list is requested');
''')

    def test_a_newer_selection_wins_over_a_stale_detail_and_keeps_the_graph(self):
        self.run_scenario(r'''
routes['/api/state'] = r => r.respond(accepted(null, {epoch: 0}));
routes['/api/mood-axis-graph'] = r => r.respond(graphBody(library));
routes['/api/tracks/summary'] = r => r.respond(summaryBody(library));
routes['/api/current'] = r => r.respond(accepted(r.body.track_id, {epoch: 0}));
const seam = boot(); await settle(); await search('Track'); await settle();
assert.equal(seam.snapshot().graphStatus, 'ready');
const shown = mounted, mountsBefore = mounts, graphAsks = asked('/api/mood-axis-graph'), listAsks = asked('/api/tracks/summary');
await chooseRow('a');
assert.ok(request('/api/tracks/a'), 'the first detail is in flight');
await chooseRow('b'); request('/api/tracks/b').respond(detailBody('b')); await settle();
request('/api/tracks/a').respond(detailBody('a')); await settle();
assert.equal(seam.snapshot().currentTrackId, 'b');
assert.match(detailText(), /Track b/, 'the stale detail of a never replaces b');
assert.doesNotMatch(detailText(), /Track a/);
assert.deepEqual(currentRows(), ['b']);
assert.equal(mounts, mountsBefore, 'a selection never replaces the graph data');
assert.strictEqual(mounted, shown);
assert.equal(asked('/api/mood-axis-graph'), graphAsks, 'a selection never reloads the graph');
assert.equal(asked('/api/tracks/summary'), listAsks, 'a selection never reloads the list');
assert.ok(nodeSize(mounted.nodes.find(node => node.id === 'b')) > nodeSize(mounted.nodes.find(node => node.id === 'a')),
  'the selected node is drawn larger');
''')

    def test_a_stale_startup_refresh_never_overwrites_a_newer_selection(self):
        self.run_scenario(r'''
routes['/api/tracks/summary'] = r => r.respond(summaryBody(library));
routes['/api/current'] = r => r.respond(accepted(r.body.track_id, {epoch: 0}));
const seam = boot();
assert.equal(asked('/api/state'), 0, 'startup waits for its first paint frame before reading state');
await settle();
request('/api/state').respond(accepted('a', {epoch: 0})); await settle();
assert.ok(request('/api/tracks/a'), 'the startup refresh asked for the detail of a');
await search('Track'); await settle();
await chooseRow('b'); request('/api/tracks/b').respond(detailBody('b')); await settle();
request('/api/tracks/a').respond(detailBody('a')); await settle();
assert.equal(seam.snapshot().currentTrackId, 'b', 'the stale refresh never restores a');
assert.match(detailText(), /Track b/);
assert.doesNotMatch(detailText(), /Track a/);
assert.equal(asked('/api/tracks/summary'), 1, 'only the search listed tracks; a refresh never fills the list');
assert.ok(!requests.some(item => item.path.startsWith('/api/candidates')));
assert.equal(mounts, 0, 'the graph was never answered, so nothing was drawn');
''')


if __name__ == '__main__':
    unittest.main()
