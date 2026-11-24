"""Opt-in real browser smoke for the bundled vanilla explorer UI.

RUN_BROWSER_SMOKE=1 PLAYWRIGHT_BROWSERS_PATH=/tmp/phase4-simple-evidence/pw-browsers \
  /tmp/phase4-simple-evidence/pw-venv/bin/python -m unittest tests.acceptance.test_explorer_browser_smoke -v
"""
import os
import threading
import unittest

from tests.acceptance.test_explorer_server import create_db
from music_analyzer.frameworks.explorer.server import create_server
from tests.support.explorer_diagnostics_page import GRAPH, SCENE, diagnostics_url, snapshot_is

# What the graph shows, read through the diagnostics seam (#146): ids, positions, edges, framing and the first score.
SHOWN_GRAPH = """() => {
  const {model, layout} = window.explorerDiagnostics.graph(), end = value => typeof value === 'object' ? value.id : value;
  return {ids: model.nodes.map(n => n.id), positions: model.nodes.map(n => [n.x, n.y, n.z]),
    edges: model.links.map(l => [end(l.source), end(l.target)]), layout, score: model.nodes[0].moodScore.raw};
}"""


@unittest.skipUnless(os.environ.get('RUN_BROWSER_SMOKE') == '1', 'opt-in Playwright Chromium smoke')
class ExplorerBrowserSmokeTests(unittest.TestCase):
    def test_mood_dropdown_changes_score_without_reframing_or_navigation(self):
        from playwright.sync_api import sync_playwright
        from tests.support.three_track_graph_db import create_three_track_graph_db
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / 'analysis.sqlite'
            ids = create_three_track_graph_db(db)
            server = create_server(str(db), port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(channel='chromium')
                    page = browser.new_page()
                    requests = []
                    page.on('request', lambda request: requests.append(request.url))
                    page.goto(diagnostics_url(f'http://127.0.0.1:{server.server_port}/'))
                    page.wait_for_function("document.querySelector('#selected-mood').options.length > 1")
                    page.wait_for_function(f'{GRAPH}.model.nodes.length === 2 && !!{SCENE}.graph')
                    graph_requests = [url for url in requests if '/api/mood-axis-graph' in url]
                    self.assertEqual(len(graph_requests), 1, 'startup automatically requests graph once')
                    self.assertIn('contract=v3', graph_requests[0])
                    page.get_by_role('searchbox', name='Search tracks by title or artist').fill('Alpha')
                    page.get_by_role('button', name='Alpha').click()
                    page.get_by_role('heading', name='Current Track').wait_for()
                    # The accepted selection owns one timed focus motion; a programmatic
                    # pose set during it is overwritten by the next frame. Compare the
                    # mood change against a settled camera, not that motion.
                    page.wait_for_function(snapshot_is('s.pendingCameraTrackId===null && !s.cameraFocusActive'))
                    page.evaluate(f'() => {{{SCENE}.graph.cameraPosition({{x:99,y:88,z:777}},{{x:20,y:30,z:40}},0);return true}}')
                    before = page.evaluate(SHOWN_GRAPH)
                    page.wait_for_timeout(150)
                    before['camera'] = page.evaluate(f'{SCENE}.graph.cameraPosition()')
                    page.click('#open-playlist')  # #233: the mood tracker lives in the playlist modal
                    page.locator('#selected-mood').select_option('relaxing')
                    page.keyboard.press('Escape')
                    page.wait_for_function(f"{GRAPH}.model.selectedMood === 'relaxing'")
                    after = page.evaluate(SHOWN_GRAPH)
                    after['camera'] = page.evaluate(f'{SCENE}.graph.cameraPosition()')
                    after['readouts'] = page.evaluate("""() => {
                        const picker=document.getElementById('mood-strip-picker'), readouts=[];
                        for(let index=0;index<=Number(picker.max);index++){
                          picker.value=String(index);picker.dispatchEvent(new Event('input'));
                          readouts.push(document.getElementById('mood-strip-value').textContent);
                        }
                        return readouts;
                    }""")
                    self.assertEqual(before['ids'], ids[:2])
                    for key in ('ids', 'positions', 'edges', 'camera', 'layout'):
                        self.assertEqual(before[key], after[key], key)
                    self.assertNotEqual(before['score'], after['score'])
                    self.assertEqual(after['positions'][1][2] - after['positions'][0][2], 144)
                    self.assertTrue(any('0.2 / 1' in readout for readout in after['readouts']), after['readouts'])
                    self.assertTrue(all(url.startswith(f'http://127.0.0.1:{server.server_port}/') for url in requests))
                    self.assertEqual(page.url, f'http://127.0.0.1:{server.server_port}/?diagnostics')
                    browser.close()
            finally:
                server.shutdown(); server.server_close()

    def test_local_ui_lists_tracks_selects_current_and_draws_map(self):
        from playwright.sync_api import sync_playwright
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / 'analysis.sqlite'
            first, second = create_db(db)
            server = create_server(str(db), port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(channel='chromium')
                    page = browser.new_page()
                    page.goto(f'http://127.0.0.1:{server.server_port}/')
                    page.get_by_role('searchbox', name='Search tracks by title or artist').wait_for()
                    self.assertEqual(page.locator('#tracks tbody tr').count(), 0)
                    self.assertEqual(page.locator('#tracks th').all_text_contents(), ['Title', 'Artist'])
                    self.assertEqual(page.get_by_role('searchbox', name='Search tracks by title or artist').count(), 1)
                    page.get_by_role('searchbox', name='Search tracks by title or artist').fill('SECOND')
                    page.wait_for_function("document.querySelectorAll('#tracks tbody tr').length === 1")
                    self.assertEqual(page.locator('#tracks tbody tr:visible').count(), 1)
                    page.get_by_role('searchbox', name='Search tracks by title or artist').fill('')
                    page.wait_for_function("document.querySelectorAll('#tracks tbody tr').length === 0")
                    page.get_by_role('searchbox', name='Search tracks by title or artist').fill('SECOND')
                    page.get_by_role('button', name='Second.flac').wait_for()
                    page.get_by_role('button', name='Second.flac').click()
                    page.get_by_role('heading', name='Current Track').wait_for()
                    self.assertEqual(page.get_by_text('Graph key / status').count(), 0)
                    self.assertEqual(page.get_by_text('Graph legend & status').count(), 0)
                    self.assertEqual(page.locator('#mood-strip-picker').count(), 1)
                    current = page.evaluate("fetch('/api/state').then(r=>r.json())")
                    self.assertEqual(current['current_track_id'], second)
                    page.locator('#graph3d canvas').wait_for()
                    scene = page.locator('#graph3d canvas').evaluate("""canvas => {
                        const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
                        const box = canvas.getBoundingClientRect();
                        return {hasWebGL: !!gl, width: Math.round(box.width), height: Math.round(box.height)};
                    }""")
                    self.assertTrue(scene['hasWebGL'])
                    self.assertGreater(scene['width'], 0)
                    self.assertGreater(scene['height'], 0)
                    browser.close()
            finally:
                server.shutdown(); server.server_close()


if __name__ == '__main__':
    unittest.main()
