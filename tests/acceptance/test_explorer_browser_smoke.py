"""Opt-in real browser smoke for the bundled vanilla explorer UI.

RUN_BROWSER_SMOKE=1 PLAYWRIGHT_BROWSERS_PATH=/tmp/phase4-simple-evidence/pw-browsers \
  /tmp/phase4-simple-evidence/pw-venv/bin/python -m unittest tests.acceptance.test_explorer_browser_smoke -v
"""
import os
import threading
import unittest

from tests.acceptance.test_explorer_server import create_db
from music_analyzer.frameworks.explorer.server import create_server


@unittest.skipUnless(os.environ.get('RUN_BROWSER_SMOKE') == '1', 'opt-in Playwright Chromium smoke')
class ExplorerBrowserSmokeTests(unittest.TestCase):
    def test_mood_dropdown_changes_score_without_reframing_or_navigation(self):
        from playwright.sync_api import sync_playwright
        from tests.acceptance.test_explorer_3d_graph_assets import create_three_track_graph_db
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
                    page.goto(f'http://127.0.0.1:{server.server_port}/')
                    page.wait_for_function("document.querySelector('#selected-mood').options.length > 1")
                    page.wait_for_function('graphModel.nodes.length === 2 && !!forceGraph')
                    page.get_by_role('button', name='Alpha.flac').click()
                    page.get_by_text('Selected heavy raw sigmoid mean score', exact=False).wait_for()
                    before = page.evaluate("""() => {
                        forceGraph.cameraPosition({x:99,y:88,z:777},{x:20,y:30,z:40},0);
                        return {ids:graphModel.nodes.map(n=>n.id), positions:graphModel.nodes.map(n=>[n.x,n.y,n.z]),
                          edges:graphModel.links.map(l=>[typeof l.source==='object'?l.source.id:l.source,typeof l.target==='object'?l.target.id:l.target]), camera:forceGraph.cameraPosition(),
                          layout:framedGraphLayout, score:graphModel.nodes[0].moodScore.raw};
                    }""")
                    page.wait_for_timeout(150)
                    before['camera'] = page.evaluate('forceGraph.cameraPosition()')
                    page.locator('#selected-mood').select_option('relaxing')
                    page.get_by_text('Selected relaxing raw sigmoid mean score', exact=False).wait_for()
                    after = page.evaluate("""() => ({ids:graphModel.nodes.map(n=>n.id),
                        positions:graphModel.nodes.map(n=>[n.x,n.y,n.z]), edges:graphModel.links.map(l=>[typeof l.source==='object'?l.source.id:l.source,typeof l.target==='object'?l.target.id:l.target]),
                        camera:forceGraph.cameraPosition(), layout:framedGraphLayout,
                        score:graphModel.nodes[0].moodScore.raw, strip:buildMoodStrip(visibleGraph,state.current_track_id)})""")
                    self.assertEqual(before['ids'], ids[:2])
                    for key in ('ids', 'positions', 'edges', 'camera', 'layout'):
                        self.assertEqual(before[key], after[key], key)
                    self.assertNotEqual(before['score'], after['score'])
                    self.assertEqual(after['positions'][1][2] - after['positions'][0][2], 288)
                    self.assertEqual(after['strip'][0]['score'], 0.2)
                    self.assertTrue(all(url.startswith(f'http://127.0.0.1:{server.server_port}/') for url in requests))
                    self.assertEqual(page.url, f'http://127.0.0.1:{server.server_port}/')
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
                    page.get_by_role('button', name='First & Friend.flac').wait_for()
                    page.get_by_role('button', name='Second.flac').click()
                    page.get_by_text('Status: completed').wait_for()
                    current = page.evaluate("fetch('/api/state').then(r=>r.json())")
                    self.assertEqual(current['current_track_id'], second)
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
