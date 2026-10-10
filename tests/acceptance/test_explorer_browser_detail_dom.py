"""Opt-in installed-wheel structural DOM evidence; identity and DTO are separate."""
import os
from pathlib import Path
import sys
import unittest

from tools.explorer_browser_diagnostic import require_memory_bound
from tools.explorer_db_detail_browser import observe_writer_attempt
from tools.explorer_browser_report import publish_browser_report


@unittest.skipUnless(os.environ.get('RUN_EXPLORER_DOM') == '1', 'explicit bounded Chromium opt-in')
class DetailDOMAcceptance(unittest.TestCase):
    def test_fabricated_metadata_and_empty_fields_cannot_succeed(self):
        require_memory_bound()
        from playwright.sync_api import sync_playwright
        assets = Path(os.environ['EXPLORER_INSTALLED_ASSETS'])
        sys.path.insert(0, str(assets.parents[3]))
        for name in list(sys.modules):
            if name == 'music_explorer' or name.startswith('music_explorer.'):
                del sys.modules[name]
        from music_explorer.frameworks.explorer.server import create_server
        import music_explorer.frameworks.explorer.server as installed_server
        self.assertTrue(Path(installed_server.__file__).is_relative_to(assets.parents[3]))
        from tools.explorer_synthetic_fixture import public_synthetic_fixture
        from tools.explorer_http_diagnostic import _running_server
        from tools.explorer_fixture_inspection import fingerprint_sqlite_files
        with public_synthetic_fixture(track_count=12, seed=70, history_count=2, allow_large=False) as fixture:
            before = fingerprint_sqlite_files(fixture['db_path'])
            with _running_server(create_server, fixture['db_path']) as url:
                with sync_playwright() as driver:
                    browser = driver.chromium.launch(channel='chromium', env=dict(os.environ,
                        XDG_CONFIG_HOME=os.environ['TMPDIR'], XDG_CACHE_HOME=os.environ['TMPDIR']))
                    try:
                        page = browser.new_page(viewport={'width': 640, 'height': 480})
                        # Genuine renderer, fresh nodes, trusted row and matching GET:
                        # only the presented DTO content is fabricated.
                        page.add_init_script("""document.addEventListener('DOMContentLoaded',()=>{
                          const real=renderDetail;
                          renderDetail=function(){return real({metadata:{common:[['title','FABRICATED PRESENTATION']],tags:[]},fields:{}});};
                        });""")
                        sample = observe_writer_attempt(page, url, 'pending-then-ready', 'verified', fixture)
                        selected = sample['detail_bridge']['selections'][-1]
                        self.assertIs(selected['is_trusted'], True)
                        self.assertIs(selected['post']['accepted'], True)
                        self.assertIs(selected['detail']['identity_matches'], True)
                        self.assertIsNone(selected['dom_identity_matches'])
                        self.assertTrue(page.locator('#detail').inner_text().endswith('Title: FABRICATED PRESENTATION'))
                        self.assertIs(selected['detail_presented'], False)
                        self.assertEqual(sample['outcome'], 'invalid_response')
                        self.assertIsNone(selected['detail_dom_ready_ms'])
                        self.assertNotIn('FABRICATED PRESENTATION', str(sample))
                    finally:
                        browser.close()
            self.assertEqual(before, fingerprint_sqlite_files(fixture['db_path']))

    def test_fresh_structure_succeeds_but_noop_and_stale_renderers_fail(self):
        require_memory_bound()
        from playwright.sync_api import sync_playwright
        assets = Path(os.environ['EXPLORER_INSTALLED_ASSETS'])
        sys.path.insert(0, str(assets.parents[3]))
        for name in list(sys.modules):
            if name == 'music_explorer' or name.startswith('music_explorer.'):
                del sys.modules[name]
        from music_explorer.frameworks.explorer.server import create_server
        import music_explorer.frameworks.explorer.server as installed_server
        self.assertTrue(Path(installed_server.__file__).is_relative_to(assets.parents[3]))
        from tools.explorer_synthetic_fixture import public_synthetic_fixture
        from tools.explorer_http_diagnostic import _running_server
        from tools.explorer_fixture_inspection import fingerprint_sqlite_files
        samples = []
        with public_synthetic_fixture(track_count=12, seed=70, history_count=2, allow_large=False) as fixture:
            before = fingerprint_sqlite_files(fixture['db_path'])
            with _running_server(create_server, fixture['db_path']) as url:
                with sync_playwright() as driver:
                    browser = driver.chromium.launch(channel='chromium', env=dict(os.environ,
                        XDG_CONFIG_HOME=os.environ['TMPDIR'], XDG_CACHE_HOME=os.environ['TMPDIR']))
                    try:
                        for fault in ('pristine', 'noop', 'stale'):
                            page = browser.new_page(viewport={'width': 640, 'height': 480})
                            if fault == 'noop':
                                page.add_init_script("document.addEventListener('DOMContentLoaded',()=>{renderDetail=function(){document.getElementById('detail').setAttribute('aria-busy','false');};});")
                            if fault == 'stale':
                                # Restore clones of previous presentation, not merely old nodes.
                                page.add_init_script("""document.addEventListener('DOMContentLoaded',()=>{
                                  const real=renderDetail;let previous=null;
                                  renderDetail=function(value){const root=document.getElementById('detail');
                                    if(previous){root.setAttribute('aria-busy','false');root.replaceChildren(...previous.map(n=>n.cloneNode(true)));}
                                    else {real(value);previous=Array.from(root.children).map(n=>n.cloneNode(true));}
                                  };
                                });""")
                            sample = observe_writer_attempt(page, url, 'latest-selection', 'verified', fixture)
                            selected = sample['detail_bridge']['selections'][-1]
                            self.assertIs(selected['is_trusted'], True)
                            self.assertIs(selected['post']['accepted'], True)
                            # GET/DTO identity never impersonates a DOM identity.
                            self.assertIs(selected['detail']['identity_matches'], True)
                            self.assertIsNone(selected['dom_identity_matches'])
                            self.assertIs(selected['detail_presented'], fault == 'pristine')
                            self.assertEqual(sample['outcome'], 'ok' if fault == 'pristine' else 'invalid_response')
                            if fault == 'noop':
                                self.assertTrue(page.locator('#detail').inner_text().startswith('Loading'))
                            if fault != 'pristine':
                                self.assertIsNone(selected['detail_dom_ready_ms'])
                            samples.append(sample)
                            page.close()
                    finally:
                        browser.close()
            unchanged = before == fingerprint_sqlite_files(fixture['db_path'])
        for sample in samples:
            sample['detail_bridge']['database_unchanged'] = unchanged
            sample['detail_bridge']['cleanup'] = dict(browser_closed=True, server_closed=True, scratch_removed=True)
        published = publish_browser_report(attempts=samples)
        self.assertEqual(published['profiles']['process-cold']['succeeded'], 1)
        self.assertEqual([s['outcome'] for s in published['samples']], ['ok', 'invalid_response', 'invalid_response'])
        for sample in published['samples']:
            selected = sample['detail_bridge']['selections'][-1]
            self.assertIsNone(selected['dom_identity_matches'])
            self.assertIn('detail_presented', selected)
