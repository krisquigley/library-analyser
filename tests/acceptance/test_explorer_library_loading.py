"""The library loading screen and the startup refresh (#146): the real page, booted as in a browser, driven as the
listener and the server would, and observed through its diagnostics seam, its DOM and its requests."""
import unittest

from tests.support.explorer_page_harness import ASSETS, PAGE
from tests.support.node_script import run_node_script

LOADING = r'''
const surface = byId('library-loading');
const statusText = () => byId('loading-status').textContent;
const asked = path => requests.filter(item => item.path === path).length;
'''


def scenario(body):
    return PAGE + '(async () => {\n' + LOADING + body + "\nconsole.log('NODE_SCRIPT_COMPLETED');\n})()" \
        ".catch(error => { console.error(error.stack); process.exitCode = 1; });"


class LibraryLoadingTests(unittest.TestCase):
    def run_scenario(self, body):
        for asset in ASSETS:
            with self.subTest(asset=str(asset)):
                run_node_script(self, scenario(body), str(asset))

    def test_startup_shows_the_selected_detail_and_leaves_the_list_empty_until_a_search(self):
        self.run_scenario(r'''
routes['/api/state'] = r => r.respond({current_track_id: 'off-page', history: ['previous'], selection_epoch: 4});
routes['/api/tracks/<id>'] = r => r.respond({handle: 'off-page', metadata: {common: [['title', 'Off Page Detail']], tags: []}, fields: {}});
const seam = boot(); await settle();
assert.equal(asked('/api/tracks/summary'), 0, 'the list stays empty until the listener searches');
assert.ok(!requests.some(item => item.url.search.includes('limit=all')), 'startup never asks for the whole library');
assert.equal(asked('/api/mood-axis-graph'), 1, 'startup asks for the graph once; the refresh adds no graph request');
assert.deepEqual(rows(), [], 'the selected detail does not fill the list');
assert.match(byId('detail').textContent, /Off Page Detail/, 'the selected detail shows without the graph');
assert.equal(seam.snapshot().currentTrackId, 'off-page');
assert.deepEqual(seam.snapshot().history, ['previous']);
assert.equal(typeof byId('track-search').oninput, 'function', 'search works without the graph');
''')

    def test_the_loading_screen_is_painted_before_the_state_request_and_reports_done(self):
        self.run_scenario(r'''
boot();
assert.match(statusText(), /Preparing/);
assert.equal(asked('/api/state'), 0, 'the loading screen can paint before the state request starts');
frame(); await flush();
assert.equal(asked('/api/state'), 1, 'after its first frame the refresh reads the library state');
request('/api/state').respond(accepted(null, {epoch: 0})); await settle();
assert.ok(surface.classList.contains('done'));
assert.equal(surface.getAttribute('aria-busy'), 'false');
''')

    def test_a_stale_refresh_never_ends_a_newer_ones_loading_and_a_failure_offers_retry(self):
        self.run_scenario(r'''
boot(); frame(); await flush();
assert.equal(asked('/api/state'), 1);
byId('loading-retry').click(); await flush();
assert.equal(asked('/api/state'), 1, 'the newer refresh also waits for its paint frame');
frame(); await flush();
assert.equal(asked('/api/state'), 2);
request('/api/state', 0).respond(accepted('old', {epoch: 0})); await flush();
assert.ok(!surface.classList.contains('done'), 'the stale refresh must not end the newer loading');
request('/api/state', 1).respond(accepted(null, {epoch: 0})); await settle();
assert.ok(surface.classList.contains('done'), 'the newest refresh ends the loading');
byId('loading-retry').click(); frame(); await flush();
request('/api/state', 2).fail(new Error('network down')); await settle();
assert.equal(surface.getAttribute('aria-busy'), 'false');
assert.match(statusText(), /Unable to load/);
assert.match(byId('loading-error').textContent, /network down/);
assert.equal(byId('loading-retry').hidden, false, 'the failure offers Retry');
''')


if __name__ == '__main__':
    unittest.main()
