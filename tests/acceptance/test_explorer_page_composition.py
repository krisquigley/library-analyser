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


    def test_preview_shows_the_drafted_playlist_from_the_current_track(self):
        self.run_scenario(r'''
routes['/api/current'] = r => r.respond(accepted(r.body.track_id));
routes['/api/playlists/preview'] = r => r.respond({
  tracks: [
    {track_id: 'b', title: 'Track b', artist: 'Public synthetic', bpm: 120, key: 'A minor', camelot: '8A', arousal: 0.4,
      energy_level: 0.5, energy_target: null},
    {track_id: 'a', title: 'Track a', artist: 'Public synthetic', bpm: 121, key: null, camelot: null, arousal: null,
      energy_level: null, energy_target: null},
  ],
  transitions: [{from_track_id: 'b', to_track_id: 'a', key_compatible: null, bpm_step_smooth: true, bpm_change: 1}],
  complete: false, warning: 'Only 2 of 10 tracks fit'});
await settle(6);
await search('b'); await settle(2);
await chooseRow('b'); await settle(4); await untilCameraSettles();
const bpmMin = byId('m3u-bpm-min'); bpmMin.value = '118'; bpmMin.onchange();
const bpmMax = byId('m3u-bpm-max'); bpmMax.value = '126'; bpmMax.onchange();
heard.length = 0;
await press('preview-playlist'); await settle(2);
const asked = request('/api/playlists/preview').url.searchParams;
assert.deepEqual([asked.get('start'), asked.get('bpm_min')], ['b', '118']);
assert.deepEqual(heard.filter(type => type.startsWith('playlist-')), ['playlist-preview-started', 'playlist-previewed']);
assert.deepEqual(heard.filter(type => type.startsWith('tag-write-')), ['tag-write-playlist-withdrawn', 'tag-write-playlist-offered']);
const cells = byId('playlist-preview-tracks').children.map(line => line.children.map(cell => cell.textContent));
assert.deepEqual(cells, [
  ['1', 'Public synthetic – Track b', '120.0', 'A minor', '0.5', '—', 'Start'],
  ['2', 'Public synthetic – Track a', '121.0', '—', '—', '—', 'Key unknown, +1.0 BPM'],
]);
assert.equal(byId('playlist-preview-status').textContent, '2 tracks. Warning: Only 2 of 10 tracks fit');
assert.equal(byId('playlist-energy-chart').getAttribute('aria-label'),
  'Energy across 2 tracks: the arc target (dashed) and the energy each track reaches (solid).');
assert.equal(requests.filter(r => r.path === '/api/playlists/m3u').length, 0, 'a preview downloads nothing');
''')


    def test_export_recipe_without_a_current_track_says_to_select_one(self):
        self.run_scenario(r'''
await settle(6);
heard.length = 0;
await press('export-playlist-recipe');
assert.deepEqual(heard, ['playlist-recipe-export-failed']);
const status = byId('playlist-recipe-export-status');
assert.deepEqual([status.textContent, status.getAttribute('role')], ['Recipe export failed: Select a start track first', 'alert']);
''')


    def test_a_saved_recipe_is_listed_on_request_and_loaded_with_its_start_track_current(self):
        self.run_scenario(r'''
routes['/api/current'] = r => r.respond(accepted(r.body.track_id));
routes['/api/playlist-recipes'] = r => r.respond({recipes: [
  {name: 'Warm-up', updated_at: '2026-11-20T10:00:00Z', problem: null},
  {name: 'Old', updated_at: '2026-11-01T10:00:00Z', problem: 'Its start track z is not an available track'}]});
routes['/api/playlist-recipes/load'] = r => r.respond({name: r.url.searchParams.get('name'), recipe: {
  format: 'playlist-recipe', version: 1, start_track_id: 'a', bpm: {min: 118, max: 126}, length: {tracks: 12},
  harmonic_mixing: {enabled: false, minimum_key_strength: 0.5}, energy_plan: [], mood_hold: null}});
await settle(6);
assert.equal(requests.filter(r => r.path.startsWith('/api/playlist-recipes')).length, 0, 'nothing is listed unasked');
await press('saved-recipes-list'); await settle(2);
assert.deepEqual(byId('saved-recipe-choice').children.map(option => [option.value, option.disabled]), [['Warm-up', false], ['Old', true]]);
heard.length = 0;
await press('saved-recipe-load'); await settle(2);
assert.equal(request('/api/playlist-recipes/load').url.searchParams.get('name'), 'Warm-up');
assert.deepEqual(heard.filter(type => type.startsWith('saved-recipe')), ['saved-recipe-loading', 'saved-recipe-loaded']);
assert.ok(heard.includes('track-chosen'), heard.join(' '));
assert.deepEqual(['m3u-bpm-min', 'm3u-bpm-max', 'm3u-count'].map(id => byId(id).value), ['118', '126', '12']);
assert.equal(byId('m3u-harmonic').checked, false);
assert.equal(byId('saved-recipe-status').textContent, 'Loaded Warm-up.');
await settle(4); await untilCameraSettles();
assert.equal(request('/api/current').body.track_id, 'a', 'owner decision A (#139): the start track becomes current');
assert.equal(seam.snapshot().currentTrackId, 'a');
assert.ok(byId('detail').innerText.includes('Track a'), 'its detail is shown');
''')


    def test_the_header_opens_one_tool_modal_at_a_time_beside_the_library_drawer(self):
        self.run_scenario(r"""
await settle(6);
assert.deepEqual([byId('library-panel').open, byId('library-panel').modal], [true, false], 'the Library starts open beside the graph');
assert.equal(byId('open-library').getAttribute('aria-expanded'), 'true');
heard.length = 0;
await press('open-playlist');
assert.deepEqual([byId('playlist-panel').open, byId('playlist-panel').modal], [true, true], 'the playlist generator is a modal');
await press('open-tag-write');
assert.equal(byId('playlist-panel').open, false, 'one modal at a time');
assert.deepEqual([byId('tag-write-panel').open, byId('library-panel').open], [true, true]);
byId('tag-write-panel').dispatch('cancel'); await flush();
assert.equal(byId('tag-write-panel').open, false, 'Esc closes the modal');
await press('open-playlist');
byId('playlist-panel').dispatch('click'); await flush();
assert.equal(byId('playlist-panel').open, false, 'a click on the backdrop closes the modal');
await press('open-playlist'); await press('close-playlist');
await press('open-library');
assert.deepEqual([byId('playlist-panel').open, byId('library-panel').open], [false, false]);
assert.equal(byId('open-library').getAttribute('aria-expanded'), 'false');
assert.deepEqual(heard.filter(type => type.startsWith('tool-panel')), ['tool-panel-opened', 'tool-panel-closed', 'tool-panel-opened',
  'tool-panel-closed', 'tool-panel-opened', 'tool-panel-closed', 'tool-panel-opened', 'tool-panel-closed', 'tool-panel-closed']);
""")

    def test_filters_take_the_drawer_and_the_playlist_generator_is_a_series_of_steps(self):
        self.run_scenario(r"""
await settle(6);
await press('open-filters');
assert.deepEqual([byId('filters-panel').open, byId('filters-panel').modal, byId('library-panel').open], [true, false, false],
  'the filters drawer takes the Library drawer\'s place');
const steps = byId('playlist-controls').children.map(node => node.id);
assert.deepEqual(steps, ['m3u-download-controls', 'playlist-step-preview', 'playlist-step-finish']);
assert.deepEqual(byId('m3u-download-controls').children.map(node => node.id), ['playlist-step-tempo', 'playlist-step-energy']);
const inFinish = walk(byId('playlist-step-finish')).map(node => node.id);
for (const id of ['download-m3u', 'export-playlist-recipe', 'saved-recipes-list']) assert.ok(inFinish.includes(id), id);
assert.ok(walk(byId('playlist-step-preview')).some(node => node.id === 'preview-playlist'));
await press('m3u-add-arc'); await flush();
assert.equal(byId('m3u-arc-0').tagName, 'DETAILS');
assert.equal(byId('m3u-arc-0').open, true, 'a new arc opens');
assert.match(byId('m3u-arc-0').children[0].textContent, /^Arc 1 · Rising energy · length not set/);
""")

    def test_a_selected_track_keeps_its_neighbours_in_focus_and_dims_the_rest_of_the_graph(self):
        self.run_scenario(r"""
library.push(track('c', 0.5, 0.1, 0.3));
routes['/api/mood-axis-graph'] = r => r.respond(graphBody(library, {links: [[0, 1, 0.9], [1, 2, 0.8]]}));
routes['/api/current'] = r => r.respond(accepted(r.body.track_id));
routes['/api/reset'] = r => r.respond(accepted(null, {epoch: 2}));
await settle(6);
await press('reload-graph'); await settle(6);
assert.equal(mounted.links.length, 2);
const colours = () => mounted.nodes.map(node => nodeColour(node));
const links = () => mounted.links.map(link => linkColour(link));
const bright = mounted.nodes.map(node => node.color);
assert.deepEqual(colours(), bright, 'nothing is dimmed before a selection');
await search('a'); await settle(2);
await chooseRow('a'); await settle(4); await untilCameraSettles();
assert.deepEqual(colours(), [bright[0], bright[1], 'rgba(120,135,160,0.1)'], 'a and its neighbour b stay bright; c is dimmed');
assert.notEqual(links()[0], 'rgba(240,240,240,0.03)');
assert.equal(links()[1], 'rgba(240,240,240,0.03)', 'the link from b to c is not one of a\'s');
await press('reset'); await settle(4);
assert.deepEqual(colours(), bright, 'clearing the selection restores the graph');
""")

    def test_the_selected_track_and_its_neighbours_are_labelled_with_title_and_artist(self):
        self.run_scenario(r"""
library.push(track('c', 0.5, 0.1, 0.3));
routes['/api/mood-axis-graph'] = r => r.respond(graphBody(library, {links: [[0, 1, 0.9], [1, 2, 0.8]]}));
routes['/api/current'] = r => r.respond(accepted(r.body.track_id));
routes['/api/reset'] = r => r.respond(accepted(null, {epoch: 2}));
routes['/api/track-labels'] = r => r.respond({labels: r.url.searchParams.getAll('track').map(id => ({track_id: id, title: '<i>Track ' + id + '</i>', artist: 'Public synthetic'}))});
await settle(6);
await press('reload-graph'); await settle(6);
const labels = () => byId('graph3d').children.filter(node => String(node.className).startsWith('graph-track-label'));
assert.deepEqual(labels(), [], 'no labels before a selection');
await search('b'); await settle(2);
await chooseRow('b'); await settle(4); await untilCameraSettles();
assert.deepEqual(request('/api/track-labels').url.searchParams.getAll('track'), ['b', 'a', 'c'], 'the selected track first, then its neighbours');
assert.deepEqual(labels().map(label => [label.className, label.textContent]), [
  ['graph-track-label selected', '<i>Track b</i> — Public synthetic'],
  ['graph-track-label', '<i>Track a</i> — Public synthetic'], ['graph-track-label', '<i>Track c</i> — Public synthetic']]);
assert.equal(requests.filter(r => r.path === '/api/track-labels').length, 1, 'asked once per selection');
await press('reset'); await settle(4);
assert.deepEqual(labels(), [], 'clearing the selection removes the labels');
""")

    def test_preview_waits_with_its_reason_until_the_playlist_recipe_is_complete(self):
        self.run_scenario(r"""
routes['/api/current'] = r => r.respond(accepted(r.body.track_id));
routes['/api/reset'] = r => r.respond(accepted(null, {epoch: 2}));
routes['/api/playlists/preview'] = r => r.respond({tracks: [], transitions: [], complete: true, warning: null});
await settle(6);
const button = byId('preview-playlist'), reason = () => byId('playlist-preview-reason').textContent;
assert.equal(button.disabled, true);
assert.equal(reason(), 'To preview: select a start track first, enter a minimum BPM, enter a maximum BPM.');
assert.deepEqual(['m3u-bpm-min', 'm3u-bpm-max'].map(id => byId(id).getAttribute('aria-required')), ['true', 'true']);
assert.equal(byId('m3u-bpm-max').getAttribute('aria-invalid'), 'true');
const type = (id, value) => { byId(id).value = value; byId(id).oninput(); };
type('m3u-bpm-min', '118'); await settle(1);
assert.equal(reason(), 'To preview: select a start track first, enter a maximum BPM.', 'checked as you type');
type('m3u-bpm-max', '126'); type('m3u-count', ''); await settle(1);
assert.equal(reason(), 'To preview: select a start track first, enter a track count or a duration.');
assert.equal(byId('m3u-count').getAttribute('aria-invalid'), 'true');
type('m3u-count', '12');
await search('b'); await settle(2);
await chooseRow('b'); await settle(4); await untilCameraSettles();
assert.deepEqual([button.disabled, reason()], [false, ''], 'a complete recipe with a start track can be previewed');
await press('preview-playlist'); await settle(2);
assert.equal(request('/api/playlists/preview').url.searchParams.get('bpm_max'), '126');
assert.equal(button.disabled, false);
await press('reset'); await settle(4);
assert.deepEqual([button.disabled, reason()], [true, 'To preview: select a start track first.']);
""")

    def test_library_results_are_rows_with_a_bpm_badge_and_arrow_keys_move_between_them(self):
        self.run_scenario(r"""
routes['/api/tracks/summary'] = r => r.respond(summaryBody(library));
await settle(6);
const tracks = byId('tracks');
assert.equal(tracks.dataset.tone, 'idle');
await search('Track'); await settle(2);
assert.equal(tracks.dataset.tone, 'results');
const rows = walk(tracks).filter(node => node.tagName === 'TR' && node.dataset.trackId);
assert.deepEqual(rows.map(row => row.dataset.trackId), ['a', 'b']);
const cells = row => row.children.map(cell => [cell.className, cell.textContent]);
assert.deepEqual(cells(rows[0]), [['track-title', 'Track a'], ['track-artist', 'Public synthetic120 BPM']], 'the graph supplies the BPM');
const buttons = rows.map(row => row.children[0].children[0]);
const body = walk(tracks).find(node => node.tagName === 'TBODY');
let prevented = false;
body.onkeydown({key: 'ArrowDown', target: buttons[0], preventDefault() { prevented = true; }});
assert.ok(prevented, 'the arrow key moves focus instead of scrolling');
""")

    def test_the_selected_track_card_opens_the_tag_write_dialog_from_its_header(self):
        self.run_scenario(r"""
await settle(6);
const dialog = byId('tag-write-panel');
assert.equal(dialog.open, false);
await press('detail-write-tags');
assert.deepEqual([dialog.open, dialog.modal], [true, true]);
assert.equal(byId('open-tag-write').getAttribute('aria-expanded'), 'true');
await press('detail-write-tags');
assert.equal(dialog.open, true, 'a second press keeps it open');
""")

    def test_tags_are_previewed_for_the_current_track_and_written_only_when_approved(self):
        self.run_scenario(r"""
routes['/api/current'] = r => r.respond(accepted(r.body.track_id));
routes['/api/tag-write/preview'] = r => r.respond({token: 'approval-1', skipped: [], changes: [
  {file: 'b.mp3', field: 'bpm', current: null, proposed: '120', replaces: false},
  {file: 'b.mp3', field: 'key', current: 'C', proposed: 'Am', replaces: true}]});
routes['/api/tag-write/apply'] = r => r.respond({outcomes: [{file: 'b.mp3', status: 'written', detail: 'BPM 120, key Am'}],
  notice: 'Rescan them with music-analyzer scan.'});
await settle(6);
await press('tag-write-preview'); await settle(2);
assert.equal(byId('tag-write-status').textContent, 'Select a track to tag first');
assert.equal(requests.filter(r => r.path.startsWith('/api/tag-write')).length, 0, 'nothing is asked without a track');
await search('b'); await settle(2);
await chooseRow('b'); await settle(4); await untilCameraSettles();
assert.equal(byId('tag-write-apply').disabled, true, 'nothing can be written before a preview');
byId('tag-write-policy').value = 'replace-existing';
heard.length = 0;
await press('tag-write-preview'); await settle(2);
const asked = request('/api/tag-write/preview').url.searchParams;
assert.deepEqual([asked.getAll('track'), asked.get('policy')], [['b'], 'replace-existing']);
assert.deepEqual(byId('tag-write-changes').children.map(row => row.children.map(cell => cell.textContent)),
  [['b.mp3', 'BPM', '(empty) → 120'], ['b.mp3', 'Key', 'C → Am (replaces)']]);
assert.equal(requests.filter(r => r.path === '/api/tag-write/apply').length, 0, 'a preview writes nothing');
await press('tag-write-apply'); await settle(2);
assert.deepEqual(request('/api/tag-write/apply').body, {token: 'approval-1'});
assert.deepEqual(heard, ['tag-write-previewing', 'tag-write-previewed', 'tag-write-applying', 'tag-write-applied']);
assert.deepEqual(byId('tag-write-report').children.map(item => item.textContent), ['b.mp3: written (BPM 120, key Am)']);
assert.equal(byId('tag-write-status').textContent, '1 written, 0 skipped, 0 failed. Rescan them with music-analyzer scan.');
assert.equal(byId('tag-write-apply').disabled, true, 'the approval is spent');
await press('tag-write-preview'); await settle(2);
assert.equal(byId('tag-write-apply').disabled, false);
await search('a'); await settle(2);
await chooseRow('a'); await settle(4); await untilCameraSettles();
assert.equal(byId('tag-write-apply').disabled, true, 'a preview of b cannot be approved once a is selected');
assert.deepEqual(byId('tag-write-changes').children, []);
assert.equal(seam.snapshot().currentTrackId, 'a');
assert.equal(requests.filter(r => r.path === '/api/tag-write/apply').length, 1);
""")


    def test_the_previewed_playlist_is_tagged_as_one_approved_action(self):
        self.run_scenario(r"""
routes['/api/current'] = r => r.respond(accepted(r.body.track_id));
routes['/api/playlists/preview'] = r => r.respond({
  tracks: [
    {track_id: 'b', title: 'Track b', artist: 'Public synthetic', bpm: 120, key: null, camelot: null, arousal: null,
      energy_level: null, energy_target: null},
    {track_id: 'a', title: 'Track a', artist: 'Public synthetic', bpm: 121, key: null, camelot: null, arousal: null,
      energy_level: null, energy_target: null}],
  transitions: [{from_track_id: 'b', to_track_id: 'a', key_compatible: null, bpm_step_smooth: true, bpm_change: 1}],
  complete: true, warning: null});
routes['/api/tag-write/preview'] = r => r.respond({token: 'approval-2', skipped: [], changes: [
  {file: 'b.mp3', field: 'bpm', current: null, proposed: '120', replaces: false},
  {file: 'a.mp3', field: 'bpm', current: null, proposed: '121', replaces: false}]});
routes['/api/tag-write/apply'] = r => r.respond({notice: 'Rescan them.', outcomes: [
  {file: 'b.mp3', status: 'written', detail: 'BPM 120'}, {file: 'a.mp3', status: 'written', detail: 'BPM 121'}]});
await settle(6);
const target = byId('tag-write-target');
assert.equal(target.children[1].disabled, true, 'no playlist to tag before a preview');
await search('b'); await settle(2);
await chooseRow('b'); await settle(4); await untilCameraSettles();
for (const [id, value] of [['m3u-bpm-min', '118'], ['m3u-bpm-max', '126']]) { byId(id).value = value; byId(id).oninput(); }
await press('preview-playlist'); await settle(2);
assert.deepEqual([target.children[1].disabled, target.children[1].textContent], [false, 'Previewed playlist (2 tracks)']);
target.value = 'previewed-playlist';
await press('tag-write-preview'); await settle(2);
assert.deepEqual(request('/api/tag-write/preview').url.searchParams.getAll('track'), ['b', 'a']);
await press('tag-write-apply'); await settle(2);
assert.deepEqual(request('/api/tag-write/apply').body, {token: 'approval-2'});
assert.equal(byId('tag-write-status').textContent, '2 written, 0 skipped, 0 failed. Rescan them.');
await press('tag-write-preview'); await settle(2);
assert.equal(byId('tag-write-apply').disabled, false);
await press('preview-playlist'); await settle(2);
assert.equal(byId('tag-write-apply').disabled, true, 'a new playlist preview discards the tag preview made for the old one');
""")


if __name__ == '__main__':
    unittest.main()
