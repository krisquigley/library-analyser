import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ExplorerLoadingRaceRegressionTests(unittest.TestCase):
    def test_refresh_selection_stale_guards_clear_current_loading_in_both_mirrored_assets(self):
        """A post-initial refresh made stale by setCurrent must not leave the banner busy forever."""
        for package in ('music_analyzer', 'music_explorer'):
            with self.subTest(package=package):
                source = (ROOT / package / 'frameworks/explorer/assets/app.js').read_text(encoding='utf-8')
                refresh_match = re.search(r'async function refresh\(\)\{(?P<body>.*?)\n\}\nfunction trackTitle', source, re.S)
                self.assertIsNotNone(refresh_match)
                refresh_body = refresh_match.group('body')
                self.assertNotIn(
                    'if(refreshToken!==refreshRequestSeq || token!==selectionRequestSeq) return;',
                    refresh_body,
                    'selection-stale refresh guards must clear the current loading surface before returning',
                )
                # The removed sidebar fetch no longer needs its own stale boundary.
                for boundary in ('await nextFrame();', "const refreshedState=await api('/api/state');", 'await refreshSelectionDependent(token);'):
                    self.assertIn(boundary + '\n    if(abortStaleRefresh(refreshToken,token)) return;', refresh_body)
                state_read = refresh_body.index("const refreshedState=await api('/api/state');")
                stale_guard = refresh_body.index('if(abortStaleRefresh(refreshToken,token)) return;', state_read)
                epoch_sync = refresh_body.index('state=syncSelectionEpoch(refreshedState);')
                self.assertLess(state_read, stale_guard)
                self.assertLess(stale_guard, epoch_sync, 'a stale state snapshot must not roll back the reset epoch')
                self.assertIn(
                    'function abortStaleRefresh(refreshToken,selectionToken){',
                    source,
                    'helper must preserve newer-refresh protection while clearing same-refresh selection staleness',
                )


if __name__ == '__main__':
    unittest.main()
