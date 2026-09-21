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
                    pixels = page.locator('#map').evaluate("canvas => Array.from(canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data).some(v => v !== 0)")
                    self.assertTrue(pixels)
                    browser.close()
            finally:
                server.shutdown(); server.server_close()


if __name__ == '__main__':
    unittest.main()
