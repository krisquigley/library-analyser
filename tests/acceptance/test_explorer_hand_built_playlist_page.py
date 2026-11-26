"""#278: the Explorer page builds a playlist by hand from the graph labels' + buttons, shows it in the strip over the
graph, keeps it in this browser, and downloads it. The real page, booted as in a browser (see the page harness)."""
import unittest

from tests.support.explorer_page_harness import ASSETS, PAGE
from tests.support.node_script import run_node_script

LIBRARY = r'''
const library = [track('a'), track('b', -0.7, 0.8, 0.2), track('c', 0.5, 0.1, 0.3)];
routes['/api/state'] = r => r.respond(accepted(null, {epoch: 0}));
routes['/api/mood-axis-graph'] = r => r.respond(graphBody(library, {links: [[0, 1, 0.9], [1, 2, 0.8]]}));
routes['/api/tracks/summary'] = r => r.respond(summaryBody(library.filter(t => t.id === r.url.searchParams.get('query'))));
routes['/api/tracks/<id>'] = r => r.respond(detailBody(r.path.split('/').pop()));
routes['/api/current'] = r => r.respond(accepted(r.body.track_id));
routes['/api/track-labels'] = r => r.respond({labels: r.url.searchParams.getAll('track').map(id => ({track_id: id, title: 'Track ' + id, artist: 'Public synthetic'}))});
const KEY = 'music-explorer.hand-built-playlist.v1';
const label = id => byId('graph3d').children.find(node => node.trackId === id);
const part = (id, className) => label(id)?.children.find(node => node.className === className);
const strip = () => byId('hand-built-playlist');
const stripRows = () => byId('hand-built-playlist-tracks').children.map(row => row.children[0].textContent);
'''


def scenario(body):
    return PAGE + '(async () => {\n' + LIBRARY + body + "\nconsole.log('NODE_SCRIPT_COMPLETED');\n})()" \
        ".catch(error => { console.error(error.stack); process.exitCode = 1; });"


class HandBuiltPlaylistPageTests(unittest.TestCase):
    def run_scenario(self, body):
        for asset in ASSETS:
            with self.subTest(asset=str(asset)):
                run_node_script(self, scenario(body), str(asset))

    def test_plus_builds_the_playlist_moves_the_selection_on_and_the_strip_downloads_it(self):
        self.run_scenario(r"""
const seam = boot();
await settle(6);
await press('reload-graph'); await settle(6);
assert.equal(strip().hidden, true, 'no strip before there is a playlist');
await search('a'); await settle(2);
await chooseRow('a'); await settle(4); await untilCameraSettles();
assert.equal(part('a', 'graph-track-label-add'), undefined, "the selected track's own label has no +");
assert.equal(part('b', 'graph-track-label-add').getAttribute('aria-label'), 'Add Track b — Public synthetic to your playlist');
part('b', 'graph-track-label-add').click(); await settle(4); await untilCameraSettles();
assert.equal(seam.snapshot().currentTrackId, 'b', 'the added track becomes the selected one');
assert.equal(kept.get(KEY), '["a","b"]');
assert.equal(strip().hidden, false);
assert.equal(byId('hand-built-playlist-heading').textContent, 'Your playlist · 2 tracks');
assert.deepEqual(stripRows(), ['1. Track a — Public synthetic', '2. Track b — Public synthetic']);
assert.deepEqual([part('a', 'graph-track-label-add').textContent, part('c', 'graph-track-label-add').textContent], ['✓', '+'],
  "around b, a is already in the playlist and c is not");
part('c', 'graph-track-label-add').click(); await settle(4); await untilCameraSettles();
assert.equal(seam.snapshot().currentTrackId, 'c');
assert.equal(kept.get(KEY), '["a","b","c"]');
byId('hand-built-playlist-tracks').children[1].children[1].click(); await settle(2);
assert.deepEqual(stripRows(), ['1. Track a — Public synthetic', '2. Track c — Public synthetic']);
assert.equal(kept.get(KEY), '["a","c"]');
routes['/api/playlists/hand-built'] = r => r.respond('#EXTM3U\n');
await press('hand-built-playlist-download'); await settle(2);
assert.deepEqual([request('/api/playlists/hand-built').method, request('/api/playlists/hand-built').body], ['POST', {track_ids: ['a', 'c']}]);
assert.equal(byId('hand-built-playlist-status').textContent, 'M3U downloaded');
await press('hand-built-playlist-clear'); await settle(2);
assert.deepEqual([strip().hidden, kept.get(KEY)], [true, '[]']);
""")

    def test_a_playlist_kept_in_this_browser_comes_back_when_the_page_loads(self):
        self.run_scenario(r"""
kept.set(KEY, '["c","a"]');
boot();
await settle(6);
assert.equal(strip().hidden, false);
assert.deepEqual(request('/api/track-labels').url.searchParams.getAll('track'), ['c', 'a']);
assert.deepEqual(stripRows(), ['1. Track c — Public synthetic', '2. Track a — Public synthetic']);
""")


if __name__ == '__main__':
    unittest.main()
