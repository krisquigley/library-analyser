"""#278: the Explorer page builds a playlist by hand from the graph labels' + buttons, shows it in the strip over the
graph, keeps it in this browser, and downloads it. #287: the strip is a table like the playlist preview's, from the
server's preview of the list. The real page, booted as in a browser (see the page harness)."""
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
// The server's preview of a hand-built list: 'gone' is no longer playable, so it is left out.
routes['/api/playlists/hand-built/preview'] = r => {
  const tracks = r.body.track_ids.filter(id => id !== 'gone').map(id => ({track_id: id, title: 'Track ' + id, artist: 'Public synthetic',
    bpm: 120, key: 'C major', camelot: '8B', arousal: 4.5, valence: null, energy_target: null, duration_seconds: 200}));
  const transitions = tracks.slice(1).map((track, place) => ({from_track_id: tracks[place].track_id, to_track_id: track.track_id,
    key_compatible: true, bpm_step_smooth: true, bpm_change: 0}));
  r.respond({tracks, transitions, complete: tracks.length === r.body.track_ids.length, warning: null});
};
const KEY = 'music-explorer.hand-built-playlist.v1';
const label = id => byId('graph3d').children.find(node => node.trackId === id);
const part = (id, className) => label(id)?.children.find(node => node.className === className);
const strip = () => byId('hand-built-playlist');
const stripLines = () => byId('hand-built-playlist-tracks').children;
const stripRows = () => stripLines().map(line => line.children.slice(1, 8).map(cell => cell.textContent).join(' | '));
const stripButton = (place, column) => stripLines()[place].children[column].children[0];
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
assert.equal(byId('hand-built-playlist-heading').textContent, 'Your playlist · 2 tracks · 6:40');
assert.deepEqual(stripRows(), ['1 | Public synthetic – Track a | 3:20 | 120.0 | C major | 4.5 | Start',
  '2 | Public synthetic – Track b | 3:20 | 120.0 | C major | 4.5 | Key compatible, 0.0 BPM']);
assert.deepEqual(request('/api/playlists/hand-built/preview').body, {track_ids: ['a', 'b']});
assert.deepEqual([part('a', 'graph-track-label-add').textContent, part('c', 'graph-track-label-add').textContent], ['✓', '+'],
  "around b, a is already in the playlist and c is not");
part('c', 'graph-track-label-add').click(); await settle(4); await untilCameraSettles();
assert.equal(seam.snapshot().currentTrackId, 'c');
assert.equal(kept.get(KEY), '["a","b","c"]');
stripButton(1, 9).click(); await settle(2);
assert.deepEqual(stripRows(), ['1 | Public synthetic – Track a | 3:20 | 120.0 | C major | 4.5 | Start',
  '2 | Public synthetic – Track c | 3:20 | 120.0 | C major | 4.5 | Key compatible, 0.0 BPM']);
const player = byId('playlist-track-player');
stripButton(1, 0).click(); await settle(2);
assert.equal(player.plays, 1, '▶ in the strip plays its track');
player.dispatch('playing'); await settle(1);
assert.deepEqual([stripButton(1, 0).textContent, stripButton(1, 0).getAttribute('aria-label')], ['❚❚', 'Pause Public synthetic – Track c']);
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
assert.deepEqual(request('/api/playlists/hand-built/preview').body, {track_ids: ['c', 'a']});
assert.deepEqual(stripRows(), ['1 | Public synthetic – Track c | 3:20 | 120.0 | C major | 4.5 | Start',
  '2 | Public synthetic – Track a | 3:20 | 120.0 | C major | 4.5 | Key compatible, 0.0 BPM']);

""")

    def test_287_a_track_no_longer_playable_says_so_and_cannot_be_played(self):
        self.run_scenario(r"""
kept.set(KEY, '["a","gone"]');
boot();
await settle(6);
assert.deepEqual(stripRows(), ['1 | Public synthetic – Track a | 3:20 | 120.0 | C major | 4.5 | Start',
  '2 | No longer playable from the library | — | — | — | — | —']);
assert.equal(stripButton(1, 0).disabled, true);
""")

    def test_292_a_tracks_name_in_the_strip_selects_it_in_the_graph(self):
        self.run_scenario(r"""
kept.set(KEY, '["c","a"]');
const seam = boot();
await settle(6);
assert.equal(seam.snapshot().currentTrackId, null);
assert.equal(stripButton(0, 2).getAttribute('aria-label'), 'Select Public synthetic – Track c in the graph');
stripButton(0, 2).click(); await settle(4); await untilCameraSettles();
assert.equal(seam.snapshot().currentTrackId, 'c', 'the track chosen in the strip is the selected one');
assert.equal(request('/api/current').body.track_id, 'c');
assert.ok(byId('detail').innerText.includes('Track c'), 'and its detail is shown');
assert.equal(kept.get(KEY), '["c","a"]', 'the playlist is unchanged');
""")

    def test_293_moving_a_track_reorders_the_playlist_kept_previewed_and_downloaded(self):
        self.run_scenario(r"""
kept.set(KEY, '["a","b","c"]');
boot();
await settle(6);
const move = (place, arrow) => stripLines()[place].children[8].children.find(button => button.textContent === arrow);
assert.deepEqual([move(0, '↑').disabled, move(2, '↓').disabled], [true, true], 'nothing moves past either end');
move(2, '↑').click(); await settle(2);
assert.equal(kept.get(KEY), '["a","c","b"]');
assert.deepEqual(requests.filter(r => r.path === '/api/playlists/hand-built/preview').at(-1).body, {track_ids: ['a', 'c', 'b']});
assert.deepEqual(stripRows().map(row => row.split(' | ').slice(0, 2).join(' ')),
  ['1 Public synthetic – Track a', '2 Public synthetic – Track c', '3 Public synthetic – Track b']);
move(0, '↓').click(); await settle(2);
assert.equal(kept.get(KEY), '["c","a","b"]');
routes['/api/playlists/hand-built'] = r => r.respond('#EXTM3U\n');
await press('hand-built-playlist-download'); await settle(2);
assert.deepEqual(request('/api/playlists/hand-built').body, {track_ids: ['c', 'a', 'b']});
""")

    def test_294_the_journey_chart_follows_the_playlist_with_a_lane_per_measure(self):
        self.run_scenario(r"""
kept.set(KEY, '["a","b"]');
routes['/api/playlists/hand-built/preview'] = r => {
  const tracks = r.body.track_ids.map((id, place) => ({track_id: id, title: 'Track ' + id, artist: 'Public synthetic',
    bpm: 120 + 4 * place, key: 'C major', camelot: '8B', arousal: 4.5, valence: 5 + place, energy_target: null, duration_seconds: 200}));
  r.respond({tracks, transitions: tracks.slice(1).map((track, place) => ({from_track_id: tracks[place].track_id,
    to_track_id: track.track_id, key_compatible: true, bpm_step_smooth: true, bpm_change: 4})), complete: true, warning: null});
};
boot();
await settle(6);
const journey = byId('playlist-journey');
assert.equal(journey.hidden, false);
assert.equal(byId('playlist-journey-caption').textContent, 'Your playlist over 6:40');
const labels = walk(journey).filter(node => node.tagName === 'LABEL').map(node => node.textContent);
assert.deepEqual(labels, ['BPM 120.0–124.0', 'Key (Camelot) 1–12', 'Arousal 3.5–5.5', 'Valence 5.0–6.0']);
const chart = byId('playlist-journey-chart');
chart.onpointermove({clientX: 790});
assert.equal(byId('playlist-journey-readout').textContent,
  'Public synthetic – Track b · 3:20–6:40 · 124.0 BPM · Key C major (8B) · Arousal 4.5 · Valence 6.0');
stripButton(1, 9).click(); await settle(2);
assert.equal(journey.hidden, true, 'one track is no journey');
""")


if __name__ == '__main__':
    unittest.main()
