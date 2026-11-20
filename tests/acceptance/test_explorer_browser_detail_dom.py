"""Opt-in installed-wheel structural DOM evidence; identity and DTO are separate."""
import os
from pathlib import Path
import sys
import unittest

from tools.explorer_browser_diagnostic import require_memory_bound
from tools.explorer_db_detail_browser import observe_writer_attempt
from tools.explorer_browser_report import publish_browser_report


# A faulty detail presentation, injected through the page's diagnostics seam (#146): a handler of the
# page's detail events that runs after the page's own and before the observer's. The page itself is unchanged.
FAULT = """document.addEventListener('DOMContentLoaded',()=>{
 const seam=window.explorerDiagnostics, detailRoot=()=>document.getElementById('detail');
 const onDetailShown=handler=>seam.subscribe('track-detail-loaded',handler);
 const onDetailLoading=handler=>{for(const type of ['track-chosen','selection-rewinding','track-detail-loading'])seam.subscribe(type,handler);};
 const fabricatedFields=title=>{const fields=document.createElement('div');
  fields.append(seam.views().trackMetadata({common:[['title',title]],tags:[]}));return fields;};
 const showFields=fields=>detailRoot().children[1].replaceWith(fields);
 """


def faulty_detail(body):
    return FAULT + body + '\n});'



@unittest.skipUnless(os.environ.get('RUN_EXPLORER_DOM') == '1', 'explicit bounded Chromium opt-in')
class DetailDOMAcceptance(unittest.TestCase):
    def test_earlier_frame_replacement_cannot_certify_detached_genuine_fields(self):
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
                        # Queued while the page handles the loaded detail, BEFORE the
                        # observer queues its own frame callback.
                        page.add_init_script(faulty_detail("""onDetailShown(()=>requestAnimationFrame(()=>
                          showFields(fabricatedFields('FABRICATED FRAME'))));"""))
                        sample = observe_writer_attempt(page, url, 'latest-selection', 'verified', fixture)
                        self.assertEqual(len(sample['detail_bridge']['selections']), 2)
                        self.assertTrue(page.locator('#detail').inner_text().endswith('Title: FABRICATED FRAME'))
                        for selected in sample['detail_bridge']['selections']:
                            self.assertIs(selected['is_trusted'], True)
                            self.assertIs(selected['post']['accepted'], True)
                            self.assertIs(selected['detail']['identity_matches'], True)
                            self.assertIsNone(selected['dom_identity_matches'])
                            self.assertIs(selected['detail_presented'], False)
                            self.assertIsNone(selected['detail_dom_ready_ms'])
                            self.assertIsNone(selected['detail_next_frame_ms'])
                        self.assertEqual(sample['outcome'], 'invalid_response')
                        self.assertIsNone(sample['elapsed_ms'])
                        self.assertNotIn('FABRICATED FRAME', str(sample))
                    finally:
                        browser.close()
            unchanged = before == fingerprint_sqlite_files(fixture['db_path'])
        self.assertTrue(unchanged)
        sample['detail_bridge']['database_unchanged'] = unchanged
        sample['detail_bridge']['cleanup'] = dict(browser_closed=True, server_closed=True, scratch_removed=True)
        published = publish_browser_report(attempts=[sample])
        self.assertEqual(published['profiles']['process-cold']['succeeded'], 0)
        self.assertEqual(published['samples'][0]['outcome'], 'invalid_response')
        self.assertNotIn('FABRICATED FRAME', str(published))
        for selected in published['samples'][0]['detail_bridge']['selections']:
            self.assertIs(selected['detail_presented'], False)
            self.assertIsNone(selected['detail_dom_ready_ms'])
            self.assertIsNone(selected['detail_next_frame_ms'])

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
                        page.add_init_script(faulty_detail("onDetailShown(()=>showFields(fabricatedFields('FABRICATED PRESENTATION')));"))
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
                                # The loaded detail is never drawn: the loading view stays, no longer busy.
                                page.add_init_script(faulty_detail("""let loading=null;
                                  onDetailLoading(()=>{loading=Array.from(detailRoot().children).map(n=>n.cloneNode(true));});
                                  onDetailShown(()=>{detailRoot().replaceChildren(...loading);});"""))
                            if fault == 'stale':
                                # Restore clones of previous presentation, not merely old nodes.
                                page.add_init_script(faulty_detail("""let previous=null;
                                  onDetailShown(()=>{const root=detailRoot();
                                    if(previous)root.replaceChildren(...previous.map(n=>n.cloneNode(true)));
                                    else previous=Array.from(root.children).map(n=>n.cloneNode(true));});"""))
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
