"""Opt-in tiny actual WebGL observation; no useful-scale or smoothness budget.

Run each method under an external 45s hard-wall/subreaper/scratch supervisor.
RUN_EXPLORER_FOCUS_BROWSER=1 and EXPLORER_BROWSER_SUPERVISED=1 are explicit
execution acknowledgements, not substitutes for the caller's enforced limits.
Reports describe public 12-node fixtures and process-cold, not disk-cold, runs.
"""
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest

from tools import explorer_browser_diagnostic as diagnostic
from tools.explorer_browser_graph_fixture import public_browser_graph_fixture
from tools.explorer_browser_report import publish_browser_report
from tools.explorer_browser_routes import public_routes


def _renderer_implementation(sample):
    observed = sample.get('webgl_context', {}).get('implementation')
    return observed if observed in ('software-swiftshader', 'software-other', 'unclassified') else 'unclassified'


@unittest.skipUnless(os.environ.get('RUN_EXPLORER_FOCUS_BROWSER') == '1',
                     'Actual tiny focus browser observation not opted in; unverified')
class TinyRealFocusObservation(unittest.TestCase):
    def setUp(self):
        self.assertEqual(os.environ.get('EXPLORER_BROWSER_SUPERVISED'), '1',
                         'Require externally enforced hard wall and descendant/scratch cleanup')
        diagnostic.require_memory_bound()
        self.output = Path(os.environ['EXPLORER_FOCUS_EVIDENCE_DIR'])
        self.output.mkdir(parents=True, exist_ok=True)

    def observe_viewport(self, width, height, label):
        report = diagnostic.collect(SimpleNamespace(
            fixture_source='browser-only', graph_profile='small', allow_large=False,
            scenario='pending-then-ready', samples=1, observer_mode='verified'),
            {'width': width, 'height': height})
        raw_sample = report['samples'][0]
        report['samples'] = publish_browser_report(attempts=report['samples'])['samples']
        report['environment']['renderer_implementation'] = _renderer_implementation(raw_sample)
        report['environment']['webgl_context'] = report['samples'][0].get('webgl_context')
        (self.output / (label + '.json')).write_text(json.dumps(report, allow_nan=False, indent=2) + '\n')
        self.assertEqual(report['attempted'], 1)
        self.assertEqual(report['succeeded'], 1)
        sample = report['samples'][0]
        self.assertIs(raw_sample['webgl'], True)
        self.assertIs(raw_sample['render']['nonempty_pixels'], True)
        self.assertEqual(sample['outcome'], 'ok')
        projection = sample['focus']['projection']
        self.assertEqual(projection['viewport']['width_px'], width)
        self.assertEqual(projection['viewport']['height_px'], height)
        self.assertEqual(projection['support_status'], 'unassessed')
        self.assertEqual(projection['usefulness_status'], 'unassessed')
        for kind in ('mesh', 'halo'):
            self.assertEqual(projection[kind]['status'], 'observed')
            self.assertGreater(projection[kind]['diameter_px'], 0)
        self.assertEqual(sample['focus']['context']['status'], 'observed')

    def test_landscape_mesh_halo_and_frustum_observed_not_usefulness_pass(self):
        self.observe_viewport(640, 480, 'landscape')

    def test_portrait_mesh_halo_and_frustum_observed_not_supported_range(self):
        self.observe_viewport(480, 640, 'portrait')

    def test_trusted_during_focus_input_orbit_and_latest_cancellation(self):
        from playwright.sync_api import sync_playwright
        fixture = public_browser_graph_fixture(profile='small', allow_large=False)
        attempts, receipt_starts = [], []
        # Two public eligible choices are required by the later trusted motion
        # actions; initial readback still observes only the first selection.
        with public_routes(fixture, 'latest-selection') as (url, release), sync_playwright() as driver:
            try:
                browser = driver.chromium.launch(channel='chromium', timeout=15000)
            except Exception as error:
                failed = publish_browser_report(attempts=[diagnostic.failed_setup_attempt(error)])
                (self.output / 'trusted-motion-setup-failed.json').write_text(json.dumps(failed, allow_nan=False, indent=2)+'\n')
                raise
            sample = None
            try:
                page = browser.new_page(viewport={'width': 640, 'height': 480})
                sample = diagnostic.observe_attempt(page, url, release, 'pending-then-ready')
                diagnostic.validate_graph_response(sample, fixture['manifest'])
                self.assertEqual(sample['outcome'], 'ok')
                page.evaluate("window.__diagnostic.contention_action='armed'")
                page.locator('#tracks tbody tr').nth(1).click()
                page.wait_for_function('cameraFocusFrame!==null')
                receipt_starts.append(page.evaluate('window.__diagnostic.input_observations.length'))
                attempts.append(diagnostic.new_input_attempt('input', 'focus'))
                page.locator('#track-search').fill('Public synthetic')
                page.wait_for_function('cameraFocusFrame!==null')
                box = page.evaluate('forceGraph.renderer().domElement.getBoundingClientRect().toJSON()')
                x, y = box['x'] + box['width'] / 2, box['y'] + box['height'] / 2
                page.mouse.move(x, y)
                receipt_starts.append(page.evaluate('window.__diagnostic.input_observations.length'))
                attempts.append(diagnostic.new_input_attempt('orbit', 'focus'))
                page.mouse.down()
                page.mouse.move(x + 12, y + 8)
                page.mouse.up()
                page.wait_for_function("window.__diagnostic.focus.motion.cancellations.some(e=>e.reason==='user-orbit')")
                page.locator('#tracks tbody tr').first.click()
                page.wait_for_function('cameraFocusFrame!==null')
                receipt_starts.append(page.evaluate('window.__diagnostic.input_observations.length'))
                attempts.append(diagnostic.new_input_attempt('selection', 'focus'))
                page.locator('#tracks tbody tr').nth(1).click()
                page.wait_for_function("state.current_track_id==='public-00001' && pendingSelectionOperation===null && document.getElementById('detail').getAttribute('aria-busy')==='false' && selectedNodeHalo.trackId===state.current_track_id && window.__diagnostic.consumed_count>=4 && window.__diagnostic.focus.motion.starts.length>=4 && window.__diagnostic.focus.motion.starts.at(-1).active_after===true && cameraFocusFrame===null")
                page.evaluate('() => new Promise(resolve=>requestAnimationFrame(resolve))')
                observed = page.evaluate('window.__diagnostic')
                sample['focus']['motion'] = observed['focus']['motion']
                # Projection above is the initial completed readback; later motion
                # chronology is retained separately, not relabeled final projection.
                scoped_receipts = [next((record for record in observed['input_observations'][start:]
                                         if record['action'] == attempt['action']), {})
                                   for start, attempt in zip(receipt_starts, attempts)]
                sample['input_observations'] = diagnostic.merge_input_observations(
                    attempts, scoped_receipts, 'ok')
                report = publish_browser_report(attempts=[sample])
                report.update(scope='public-synthetic-browser-only',
                              scenario='trusted-motion-after-initial-readback',
                              projection_scope='initial-completed-readback',
                              graph_fixture=fixture['manifest'],
                              latency_budget_result='not_asserted',
                              browser_evidence='real-playwright-chromium',
                              environment={'browser': {'engine': 'chromium', 'version': browser.version},
                                           'renderer_implementation': _renderer_implementation(sample),
                                           'webgl_context': report['samples'][0].get('webgl_context'),
                                           'viewport': {'width': 640, 'height': 480}},
                              attempted=1, succeeded=int(sample['outcome']=='ok'))
                receipts = report['samples'][0]['input_observations']
                self.assertEqual([record['action'] for record in receipts], ['input', 'orbit', 'selection'])
                for record in receipts:
                    self.assertIs(record['is_trusted'], True)
                    self.assertEqual(record['phase_at_attempt'], 'focus')
                    self.assertEqual(record['phase_at_receipt'], 'focus')
                    self.assertEqual(record['outcome'], 'ok')
                reasons = [event['reason'] for event in report['samples'][0]['focus']['motion']['cancellations']]
                self.assertIn('user-orbit', reasons)
                self.assertIn('new-selection', reasons)
                (self.output / 'trusted-motion.json').write_text(json.dumps(report, allow_nan=False, indent=2)+'\n')
            except Exception as error:
                retained = dict(sample or diagnostic.failed_setup_attempt(error))
                retained['outcome'] = 'timeout' if type(error).__name__ == 'TimeoutError' else 'invalid_response'
                retained['elapsed_ms'] = None  # Initial readback is not motion completion.
                retained['failures'] = [*retained.get('failures', []),
                                        {'flow': 'lifecycle', 'outcome': retained['outcome']}]
                try:
                    partial = page.evaluate('window.__diagnostic') or {}
                except Exception:
                    partial = {}
                if partial.get('focus', {}).get('motion'):
                    retained['focus'] = {**retained.get('focus', {}),
                                         'motion': partial['focus']['motion']}
                scoped_receipts = [next((record for record in partial.get('input_observations', [])[start:]
                                         if record['action'] == attempt['action']), {})
                                   for start, attempt in zip(receipt_starts, attempts)]
                retained['input_observations'] = diagnostic.merge_input_observations(
                    attempts, scoped_receipts, retained['outcome'])
                failed = publish_browser_report(attempts=[retained])
                failed.update(scope='public-synthetic-browser-only',
                              scenario='trusted-motion-after-initial-readback',
                              projection_scope='initial-completed-readback', attempted=1, succeeded=0,
                              graph_fixture=fixture['manifest'],
                              environment={'browser': {'engine': 'chromium', 'version': browser.version},
                                           'renderer_implementation': _renderer_implementation(retained),
                                           'webgl_context': failed['samples'][0].get('webgl_context'),
                                           'viewport': {'width': 640, 'height': 480}})
                (self.output / 'trusted-motion-failed.json').write_text(json.dumps(failed, allow_nan=False, indent=2)+'\n')
                raise
            finally:
                browser.close()
