import json
import shutil
import tempfile
import unittest
from pathlib import Path

from music_analyzer.frameworks.explorer.server import create_server


from tests.support.node_script import run_node_script
from tests.support.explorer_app_bundle import explorer_app_script

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_JS = explorer_app_script(REPO_ROOT / 'music_analyzer' / 'frameworks' / 'explorer' / 'assets' / 'app' / 'main' / 'main.js')


from tests.support.three_track_graph_db import create_three_track_graph_db


class Explorer3DGraphAssetTests(unittest.TestCase):
    def test_projection_endpoint_exposes_all_library_tracks_for_unbounded_initial_graph(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / 'analysis.sqlite'
            ids = create_three_track_graph_db(db)
            server = create_server(str(db), port=0)
            try:
                # Exercise the API through the handler helper without depending on a browser.
                import threading
                from urllib.request import urlopen
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                with urlopen(f'http://127.0.0.1:{server.server_port}/api/state', timeout=5) as response:
                    state = json.loads(response.read().decode('utf-8'))
                self.assertIsNone(state['current_track_id'])
                with urlopen(f'http://127.0.0.1:{server.server_port}/api/tracks?limit=all', timeout=5) as response:
                    listing = json.loads(response.read().decode('utf-8'))
                self.assertEqual({track['handle'] for track in listing['tracks']}, set(ids))
                with urlopen(f'http://127.0.0.1:{server.server_port}/api/projection', timeout=5) as response:
                    projection = json.loads(response.read().decode('utf-8'))
                self.assertEqual({track['track_id'] for track in projection['tracks']}, set(ids))
                self.assertIn('z', projection['tracks'][0])
                self.assertIn('3d_coordinate_policy', projection['policy_versions'])
            finally:
                server.shutdown(); server.server_close()

    def test_static_html_does_not_instruct_manual_graph_loading_in_both_mirrored_assets(self):
        for package in ('music_analyzer', 'music_explorer'):
            with self.subTest(package=package):
                html = (REPO_ROOT / package / 'frameworks/explorer/assets/index.html').read_text(encoding='utf-8')
                self.assertNotIn('initial graph shows the whole library', html)
                self.assertNotIn('Use Load graph', html, 'startup loads the graph without a manual step')

    def test_undo_and_reset_still_force_complete_ui_refresh(self):
        app = APP_JS.read_text()
        self.assertIn('async function applyHistorySelection(action){if(await trackSelection.rewind(action)) await refresh();}', app)
        use_case = (REPO_ROOT / 'music_explorer/frameworks/explorer/assets/app/application/select-track/select-track.js').read_text()
        history = use_case[use_case.index('async function rewind(action) {'):use_case.index('function loadDetail(generation) {')]
        boundaries = (
            'const generation = ++latestGeneration;',
            'const accepted = await explorerApi.applyHistory(action);',
            'if (generation !== latestGeneration) return false;',
            'accept(accepted);',
            'return true;',
        )
        previous = -1
        for boundary in boundaries:
            self.assertIn(boundary, history)
            current = history.index(boundary)
            self.assertGreater(current, previous, 'history must guard stale responses before epoch sync and refresh')
            previous = current
        self.assertIn('explorerApi.chooseCurrentTrack({trackId, selectionToken, selectionEpoch: epoch,', use_case)
        self.assertIn("document.getElementById('undo').onclick=()=>applyHistorySelection('undo');", app)
        self.assertIn("document.getElementById('reset').onclick=()=>applyHistorySelection('reset');", app)

    def test_detail_scores_are_compact_bars_not_dials(self):
        """#236 replaces the score dials with compact bars: label, bar, raw value."""
        style = (REPO_ROOT / 'music_analyzer/frameworks/explorer/assets/style.css').read_text()
        self.assertIn('#detail .score-bar{display:flex;', style)
        self.assertIn('#detail .score-bar-fill{', style)
        for retired in ('.score-gauge', '.score-needle', '.score-tick', '--dial-'):
            self.assertNotIn(retired, style)

    def test_browser_startup_source_leaves_sidebar_empty_until_search(self):
        for app in (APP_JS, explorer_app_script(REPO_ROOT / 'music_explorer/frameworks/explorer/assets/app/main/main.js')):
            with self.subTest(app=app):
                source = app.read_text(encoding='utf-8')
                start = source.index('async function refresh()')
                refresh_source = source[start:source.index('\n}\n', start)]
                self.assertNotIn("/api/tracks/summary", refresh_source)
                self.assertNotIn("/api/tracks?limit=all", refresh_source)
                self.assertNotIn("/api/mood-axis-graph", refresh_source, 'startup refresh must not request graph before user clicks Load graph')
                self.assertIn('function loadGraph(){return graphLoad.load();}', source)
                self.assertNotIn("button.id='load-graph'", source)
                self.assertNotIn("'Load graph'", source)

    def test_mirrored_browser_assets_advertise_explicit_m3u_download_without_startup_fetch(self):
        for app in (APP_JS, explorer_app_script(REPO_ROOT / 'music_explorer/frameworks/explorer/assets/app/main/main.js')):
            with self.subTest(app=app):
                source = app.read_text(encoding='utf-8')
                self.assertIn('download-m3u', source, 'mirrored Explorer assets must expose an explicit Download M3U button')
                self.assertIn('/api/playlists/m3u', source, 'browser assets must call the M3U endpoint only from the explicit download action')
                startup_slice = source[source.index('async function refresh()'):source.index('function graphQueryFromControls()') if 'function graphQueryFromControls()' in source else source.index('function renderTracks')]
                self.assertNotIn('/api/playlists/m3u', startup_slice, 'initial refresh must not auto-fetch M3U playlists')


if __name__ == '__main__':
    unittest.main()
