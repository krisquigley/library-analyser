"""Tiny actual WebGL regression: registered search callback vs delayed POST.

Opt-in only; caller must externally enforce memory/scratch/hard-wall cleanup.
Uses twelve public synthetic nodes, never private data or useful-scale claims.
"""
import json
import os
from pathlib import Path
import unittest

from tools import explorer_browser_diagnostic as diagnostic
from tools.explorer_browser_graph_fixture import public_browser_graph_fixture
from tools.explorer_browser_routes import public_routes


POSE = """() => {
 const c=forceGraph.camera(), t=forceGraph.controls();
 return {position:c.position.toArray(),target:t.target.toArray(),up:c.up.toArray(),
 quaternion:c.quaternion.toArray(),zoom:c.zoom,
 settings:Object.fromEntries(['enabled','staticMoving','dynamicDampingFactor',
 'rotateSpeed','zoomSpeed','panSpeed','noZoom','noPan','noRotate','minDistance',
 'maxDistance'].map(k=>[k,t[k]]))};
}"""


@unittest.skipUnless(os.environ.get('RUN_EXPLORER_PENDING_SEARCH_BROWSER') == '1',
                     'Real Chromium delayed-search regression not opted in')
class PendingSearchManualOrbitBrowserTests(unittest.TestCase):
    def test_registered_search_post_then_trusted_orbit_preserves_manual_camera(self):
        from playwright.sync_api import sync_playwright
        self.assertEqual(os.environ.get('EXPLORER_BROWSER_SUPERVISED'), '1')
        diagnostic.require_memory_bound()
        output = Path(os.environ['EXPLORER_FOCUS_EVIDENCE_DIR'])
        output.mkdir(parents=True, exist_ok=True)
        artifact = output / 'pending-search-manual-orbit.json'
        self.assertFalse(artifact.exists(), 'Never overwrite existing evidence')
        evidence = {'scope': '12-public-synthetic-nodes', 'status': 'started'}
        fixture = public_browser_graph_fixture(profile='small', allow_large=False)
        with public_routes(fixture, 'latest-selection') as (url, release), sync_playwright() as driver:
            browser = None
            try:
                browser = driver.chromium.launch(channel='chromium', timeout=15000)
                evidence['browser_version'] = browser.version
                page = browser.new_page(viewport={'width': 640, 'height': 480})
                page.set_default_timeout(10000)
                pending, detail_requests = [], []
                page.on('request', lambda request: detail_requests.append(request.url)
                        if '/api/tracks/public-' in request.url else None)
                page.route('**/api/current', lambda route: pending.append(route))
                release.set()
                page.goto(url, wait_until='domcontentloaded')
                page.wait_for_function("graphLoadState.status==='ready' && forceGraph.graphData().nodes.length===12")
                page.locator('#track-search').fill('Public synthetic')
                page.locator('#tracks tbody tr button').first.wait_for()
                # Allow the vendor's initial renderer/camera setup before manual pose.
                page.wait_for_timeout(1000)
                page.evaluate("""() => {
                  const c=forceGraph.camera(),t=forceGraph.controls();
                  Object.assign(t,{enabled:true,staticMoving:true,minDistance:350,maxDistance:600});
                  const direction=c.position.clone().sub(t.target).normalize();
                  c.position.copy(t.target).add(direction.multiplyScalar(450));
                  c.zoom=3.25;c.updateProjectionMatrix();t.update();
                  window.__pendingOrbitReceipts=[];
                  forceGraph.renderer().domElement.addEventListener('pointerdown',e=>
                    window.__pendingOrbitReceipts.push({isTrusted:e.isTrusted,type:e.type}));
                }""")
                before = page.evaluate(POSE)
                # This click invokes the actual button.onclick registered by renderTracks.
                page.locator('#tracks tbody tr button').first.click()
                page.wait_for_function('pendingSelectionOperation!==null')
                self.assertEqual(len(pending), 1)
                evidence['post'] = json.loads(pending[0].request.post_data)
                self.assertEqual(evidence['post']['track_id'], 'public-00000')
                box = page.evaluate('forceGraph.renderer().domElement.getBoundingClientRect().toJSON()')
                x, y = box['x'] + box['width']/2, box['y'] + box['height']/2
                page.mouse.move(x, y)
                page.mouse.down()
                page.mouse.move(x + 25, y + 15, steps=3)
                page.mouse.up()
                page.evaluate('() => new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
                manual = page.evaluate(POSE)
                evidence.update(before=before, manual=manual,
                                trusted_receipts=page.evaluate('window.__pendingOrbitReceipts'))
                self.assertTrue(evidence['trusted_receipts'])
                self.assertTrue(all(r['isTrusted'] for r in evidence['trusted_receipts']))
                self.assertNotEqual(before['position'], manual['position'], 'Actual rendered orbit must move camera')
                self.assertEqual(manual['zoom'], 3.25)
                radius = sum((p-t)**2 for p,t in zip(manual['position'], manual['target']))**0.5
                evidence['manual_radius'] = radius
                self.assertGreaterEqual(radius, 350)
                self.assertLessEqual(radius, 600)
                pending[0].fulfill(status=200, content_type='application/json', body=json.dumps(
                    {'current_track_id':'public-00000','history':[],'selection_epoch':0}))
                page.wait_for_function("state.current_track_id==='public-00000' && pendingSelectionOperation===null && document.getElementById('detail').getAttribute('aria-busy')==='false' && selectedNodeHalo.trackId==='public-00000'")
                page.wait_for_timeout(1000)
                final = page.evaluate(POSE)
                evidence.update(final=final, detail=page.locator('#detail').inner_text(),
                                halo=page.evaluate('selectedNodeHalo.trackId'),
                                camera_focus_active=page.evaluate('cameraFocusFrame!==null'),
                                webgl=page.evaluate("!!forceGraph.renderer().getContext().getParameter(forceGraph.renderer().getContext().VERSION)"))
                self.assertTrue(evidence['webgl'])
                evidence['detail_requests'] = detail_requests
                self.assertEqual(detail_requests, [url + 'api/tracks/public-00000'])
                self.assertIn('Current Track', evidence['detail'])
                self.assertEqual(final, manual, 'Late accepted search must not reclaim manual camera intent')
                self.assertFalse(evidence['camera_focus_active'])
                evidence['status'] = 'passed'
            except Exception as error:
                evidence.update(status='failed', error=str(error))
                raise
            finally:
                artifact.write_text(json.dumps(evidence, allow_nan=False, indent=2)+'\n')
                if browser is not None:
                    browser.close()


if __name__ == '__main__':
    unittest.main()
