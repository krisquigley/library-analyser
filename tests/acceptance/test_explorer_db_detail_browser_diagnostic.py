"""Issue70 PR C RED: selected-detail observation publication bridge.

Default six tests are tiny mocked-composition/supplied-observation contracts,
NOT browser evidence.
They use the existing publication seam; no proposed module/import is required.
The opt-in tests construct the real owned writer-v10 catalogue, serve actual
packaged assets with create_server and drive Chromium/WebGL. This is correctness
only, not speed evidence. Run those tests under an external hard-wall, subreaper,
tracked-descendant SIGKILL supervisor with core=0, 32MiB file/128MiB aggregate
browser scratch limits and <=4GiB/zero-swap/groupOOM cgroup. No large profile.

Without a server observer, server phase scopes remain unavailable. Browser DOM
mutation and next-frame proxy are separate; neither means physical paint/GPU.
Only tests change: supplied observations cannot certify real browser acceptance.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest

from music_explorer.frameworks.explorer.server import create_server
from tools.explorer_browser_diagnostic import (collect, failed_setup_attempt,
                                               publish_browser_report, require_memory_bound)
from tools.explorer_fixture_inspection import fingerprint_sqlite_files
from tools.explorer_http_diagnostic import _running_server
from tools.explorer_synthetic_fixture import public_synthetic_fixture


def writer_args():
    return SimpleNamespace(fixture_source='writer-v10', track_count=12, seed=70,
                           history_count=2, allow_large=False, graph_profile='small',
                           scenario='pending-then-ready', samples=1, observer_mode='verified')


def bridge_observation():
    """Deterministic mock contract, no database/DOM/performance claim."""
    return {
        'fixture': {'source': 'public-synthetic-sqlite', 'schema_version': 10, 'track_count': 12,
                    'seed': 70, 'history_count': 2},
        'server': 'packaged-explorer-loopback',
        'database_unchanged': True,
        'initial_summary_requests': 0,
        'unrelated_detail_requests': 0,
        'graph_requests': 1,
        'graph_outcome': 'ok',
        'latest_selection_sequence': 1,
        'server_phases': {'status': 'unavailable', 'clock': None, 'spans': None},
        'cleanup': {'browser_closed': True, 'server_closed': True,
                    'scratch_removed': True},
        'selections': [{
            'sequence': 1, 'clock': 'browser-performance',
            'receipt_ms': 5, 'loading_dom_ms': 6, 'loading_frame_ms': 8,
            'loading_frame_was_busy': True,
            'post': {'request_id': 'request-1', 'request_ms': 7,
                     'headers_ms': 9, 'body_ms': 10, 'parse_ms': 11,
                     'status': 200, 'accepted': True, 'identity_matches': True},
            'detail': {'request_id': 'request-2', 'request_ms': 12,
                       'headers_ms': 13, 'body_ms': 14, 'parse_ms': 15,
                       'status': 200, 'identity_matches': True},
            'detail_dom_ready_ms': 16, 'detail_next_frame_ms': 17,
        }],
    }


def publish(bridge, outcome='ok'):
    return publish_browser_report(attempts=[{
        'profile': 'process-cold', 'outcome': outcome,
        'elapsed_ms': (bridge['selections'][-1]['detail_next_frame_ms'] -
                       bridge['selections'][-1]['receipt_ms']) if outcome == 'ok' else None,
        'detail_bridge': bridge,
    }])


class DBDetailBrowserBridgeContracts(unittest.TestCase):
    def published_bridge(self, report):
        sample = report['samples'][0]
        self.assertIn('detail_bridge', sample,
                      'selected-detail bridge evidence is silently discarded by existing publication')
        return sample['detail_bridge']

    def test_uses_writer_fixture_and_actual_packaged_server(self):
        # Explicit new outward mode on the existing collect seam. Baseline
        # ignores it and silently uses synthetic routes; no missing import RED.
        args = writer_args()
        driver = Mock()
        driver.chromium.launch.return_value.version = 'contract-only'
        driver.chromium.launch.return_value.new_page.return_value.evaluate.return_value = True
        playwright = Mock()
        playwright.__enter__ = Mock(return_value=driver)
        playwright.__exit__ = Mock(return_value=False)
        api = SimpleNamespace(sync_playwright=Mock(return_value=playwright))
        with patch.dict(sys.modules, {'playwright.sync_api': api}), \
             patch('tools.explorer_browser_diagnostic.require_memory_bound'), \
             patch('tools.explorer_synthetic_fixture.public_synthetic_fixture',
                   wraps=public_synthetic_fixture) as writer, \
             patch('music_explorer.frameworks.explorer.server.create_server',
                   wraps=create_server) as server, \
             patch('tools.explorer_browser_diagnostic.observe_attempt',
                   return_value=failed_setup_attempt(TimeoutError())):
            report = collect(args, {'width': 1280, 'height': 720})
        driver.chromium.launch.return_value.close.assert_called_once()
        self.assertEqual(writer.call_count, 1,
                         'writer-v10 mode silently used browser-only synthetic routes')
        self.assertEqual(server.call_count, 1,
                         'writer mode must own the actual packaged Explorer server')
        self.assertEqual(report['scope'], 'public-synthetic-sqlite-browser')

    def test_accepted_post_precedes_single_matching_detail(self):
        observation = bridge_observation()
        selected = self.published_bridge(publish(observation))['selections'][0]
        self.assertTrue(selected['post']['accepted'])
        self.assertTrue(selected['detail']['identity_matches'])
        self.assertNotEqual(selected['post']['request_id'], selected['detail']['request_id'])
        # Only compare operands on the same browser clock, never host/server time.
        self.assertEqual(selected['clock'], 'browser-performance')
        self.assertLessEqual(selected['post']['parse_ms'], selected['detail']['request_ms'])
        self.assertLessEqual(selected['detail']['parse_ms'], selected['detail_dom_ready_ms'])
        self.assertLessEqual(selected['detail_dom_ready_ms'], selected['detail_next_frame_ms'])
        self.assertNotEqual(selected['detail']['parse_ms'], selected['detail_dom_ready_ms'])
        self.assertNotEqual(selected['detail_dom_ready_ms'], selected['detail_next_frame_ms'])
        # A GET issued before POST acceptance is not a successful detail bridge.
        invalid = deepcopy(observation)
        invalid['selections'][0]['detail']['request_ms'] = 8
        self.assertEqual(publish(invalid)['profiles']['process-cold']['succeeded'], 0)

    def test_no_initial_summary_or_unrelated_detail_graph_refetch(self):
        for field in ('initial_summary_requests', 'unrelated_detail_requests', 'graph_requests'):
            with self.subTest(field=field):
                observation = bridge_observation()
                observation[field] += 1
                report = publish(observation)
                self.assertEqual(report['profiles']['process-cold']['succeeded'], 0,
                                 'forbidden startup/refetch inventory is still published as success')
        result = self.published_bridge(publish(bridge_observation()))
        self.assertEqual((result['initial_summary_requests'], result['unrelated_detail_requests'],
                          result['graph_requests']), (0, 0, 1))

    def test_graph_failure_does_not_block_detail_and_latest_selection(self):
        observation = bridge_observation()
        observation['graph_outcome'] = 'http_error'
        latest = deepcopy(observation['selections'][0])
        latest['sequence'] = 2
        for field in ('receipt_ms', 'loading_dom_ms', 'loading_frame_ms',
                      'detail_dom_ready_ms', 'detail_next_frame_ms'):
            latest[field] += 20
        for phase in ('post', 'detail'):
            latest[phase]['request_id'] = 'request-' + ('3' if phase == 'post' else '4')
            for field in ('request_ms', 'headers_ms', 'body_ms', 'parse_ms'):
                latest[phase][field] += 20
        observation['selections'].append(latest)
        observation['latest_selection_sequence'] = 2
        report = publish(observation)
        result = self.published_bridge(report)
        self.assertEqual(result['graph_outcome'], 'http_error')
        self.assertEqual(result['latest_selection_sequence'], 2)
        self.assertEqual(len(result['selections']), 2)
        self.assertEqual(report['profiles']['process-cold']['succeeded'], 1,
                         'graph failure alone must not classify verified selected detail as failed')

    def test_rejected_post_or_invalid_detail_cannot_report_success(self):
        for phase, field, value in (('post', 'accepted', False),
                                    ('post', 'identity_matches', False),
                                    ('detail', 'identity_matches', False),
                                    ('detail', 'status', 500)):
            with self.subTest(phase=phase, field=field):
                observation = bridge_observation()
                observation['selections'][0][phase][field] = value
                report = publish(observation)
                self.assertEqual(report['profiles']['process-cold']['succeeded'], 0,
                                 'rejected/mismatched selected-detail attempt published as success')
                self.assertNotEqual(report['samples'][0]['outcome'], 'ok')

    def test_timeout_retains_partial_evidence_and_owned_cleanup(self):
        observation = bridge_observation()
        selected = observation['selections'][0]
        selected['post'].update(headers_ms=None, body_ms=None, parse_ms=None,
                                status=None, accepted=None, identity_matches=None)
        selected['detail'] = None
        selected['detail_dom_ready_ms'] = selected['detail_next_frame_ms'] = None
        report = publish(observation, 'timeout')
        self.assertEqual(report['attempted'], 1)
        self.assertEqual(report['samples'][0]['outcome'], 'timeout')
        result = self.published_bridge(report)
        self.assertEqual(result['selections'][0]['receipt_ms'], 5)
        self.assertEqual(result['selections'][0]['post']['request_ms'], 7)
        self.assertIsNone(result['selections'][0]['detail'])
        self.assertEqual(result['cleanup'], observation['cleanup'])
        self.assertIsNone(result['server_phases']['spans'])


@unittest.skipUnless(os.environ.get('RUN_EXPLORER_DB_DETAIL_BROWSER_DIAGNOSTIC') == '1',
                     'opt-in actual writer/packaged-server Chromium gate; skipped is not acceptance')
class RealWriterPackagedBrowserBridge(unittest.TestCase):
    def test_diagnostic_owns_writer_and_packaged_server_in_real_browser_mode(self):
        require_memory_bound()
        self.assertEqual(os.environ.get('EXPLORER_BROWSER_SUPERVISED'), '1')
        with patch('tools.explorer_synthetic_fixture.public_synthetic_fixture',
                   wraps=public_synthetic_fixture) as writer, \
             patch('music_explorer.frameworks.explorer.server.create_server',
                   wraps=create_server) as server:
            report = collect(writer_args(), {'width': 1280, 'height': 720})
        self.assertEqual(report['succeeded'], 1,
                         'BLOCKED: prerequisite real Chromium tiny lifecycle failed')
        self.assertEqual(writer.call_count, 1,
                         'real diagnostic ignored writer-v10 input and ran synthetic routes')
        self.assertEqual(server.call_count, 1)
        self.assertEqual(report['scope'], 'public-synthetic-sqlite-browser')

    def test_two_samples_have_isolated_server_selection_state(self):
        require_memory_bound()
        self.assertEqual(os.environ.get('EXPLORER_BROWSER_SUPERVISED'), '1')
        installed_root = os.environ.get('EXPLORER_INSTALLED_WHEEL_ROOT')
        self.assertIsNotNone(installed_root, 'BLOCKED: installed-wheel verification required')
        import music_explorer.frameworks.explorer.server as packaged_server
        self.assertTrue(Path(packaged_server.__file__).is_relative_to(Path(installed_root)))
        for profile in ('process-cold', 'warm'):
            with self.subTest(profile=profile):
                args = writer_args()
                args.samples = 2
                args.sample_profile = profile
                with patch('music_explorer.frameworks.explorer.server.create_server',
                           wraps=create_server) as server:
                    report = collect(args, {'width': 1280, 'height': 720})
                # Retain sanitized evidence even when the success assertion is RED.
                print('TWO_SAMPLE_REPORT ' + json.dumps({key: report[key] for key in
                      ('attempted', 'succeeded', 'samples', 'failure_counts', 'warmup')}), flush=True)
                self.assertEqual([sample['outcome'] for sample in report['samples']], ['ok', 'ok'])
                self.assertEqual((report['attempted'], report['succeeded']), (2, 2))
                self.assertEqual(server.call_count, 2)
                self.assertEqual(report['failure_counts'], {})
                self.assertEqual(report['warmup']['completed'], 2 if profile == 'warm' else 0)
                for sample in report['samples']:
                    bridge = sample['detail_bridge']
                    self.assertEqual((bridge['initial_summary_requests'],
                                      bridge['unrelated_detail_requests'], bridge['graph_requests']),
                                     (0, 0, 1))
                    self.assertEqual(len(bridge['selections']), 1)
                    selected = bridge['selections'][0]
                    self.assertTrue(selected['post']['accepted'])
                    self.assertTrue(selected['post']['identity_matches'])
                    self.assertTrue(selected['detail']['identity_matches'])
                    self.assertTrue(bridge['database_unchanged'])
                    self.assertTrue(all(bridge['cleanup'].values()))
                    self.assertCountEqual(
                        [(r['method'], r['route']) for r in sample['requests']],
                        [('GET', '/api/mood-axis-graph'), ('GET', '/api/state'),
                         ('GET', '/api/tracks/summary'), ('POST', '/api/current'),
                         ('GET', '/api/tracks/<id>')])
                    self.assertTrue(all(r['status'] == 200 for r in sample['requests']))

    def test_selection_time_unrelated_detail_still_rejects_success(self):
        require_memory_bound()
        self.assertEqual(os.environ.get('EXPLORER_BROWSER_SUPERVISED'), '1')
        from tools.explorer_browser_diagnostic import observe_attempt

        def inject_unrelated_detail(page, *args, **kwargs):
            page.add_init_script("""document.addEventListener('click', event => {
                if (event.target.closest('#tracks tbody tr')) queueMicrotask(() => {
                    fetch('/api/tracks/' + encodeURIComponent(trackSummaryPage.tracks[1].handle));
                });
            }, true);""")
            return observe_attempt(page, *args, **kwargs)

        with patch('tools.explorer_browser_diagnostic.observe_attempt',
                   side_effect=inject_unrelated_detail):
            report = collect(writer_args(), {'width': 1280, 'height': 720})
        self.assertEqual(report['succeeded'], 0)
        self.assertEqual(report['samples'][0]['outcome'], 'invalid_response')
        self.assertGreater(report['samples'][0]['detail_bridge']['unrelated_detail_requests'], 0)
        self.assertTrue(report['samples'][0]['detail_bridge']['database_unchanged'])
        self.assertTrue(all(report['samples'][0]['detail_bridge']['cleanup'].values()))

    def test_tiny_writer_server_chromium_selected_detail_publication(self):
        # External containment is mandatory, and absence is BLOCKED not RED.
        require_memory_bound()
        self.assertEqual(os.environ.get('EXPLORER_BROWSER_SUPERVISED'), '1',
                         'BLOCKED: external scratch/descendant/hard-wall supervisor required')
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory(prefix='db-detail-browser-') as scratch:
            env = dict(os.environ, XDG_CONFIG_HOME=scratch + '/config',
                       XDG_CACHE_HOME=scratch + '/cache')
            with public_synthetic_fixture(track_count=12, seed=70, history_count=2,
                                          allow_large=False) as fixture:
                before = fingerprint_sqlite_files(fixture['db_path'])
                with _running_server(create_server, fixture['db_path']) as url:
                    with sync_playwright() as driver:
                        browser = driver.chromium.launch(channel='chromium', timeout=15000, env=env)
                        try:
                            page = browser.new_page(viewport={'width': 1280, 'height': 720})
                            self.assertTrue(page.evaluate("!!document.createElement('canvas').getContext('webgl2')"),
                                            'BLOCKED: Chromium WebGL unavailable, not behavioral RED')
                            page.set_default_timeout(10000)
                            page.add_init_script(_DETAIL_PROBE)
                            page.goto(url, wait_until='domcontentloaded')
                            page.wait_for_function("state.selection_epoch!=null && graphLoadState.status==='ready'")
                            initial = page.evaluate("window.__dbBridge.requests.filter(r=>r.route==='/api/tracks/summary').length")
                            page.evaluate(_WRAP_DETAIL)
                            page.locator('#track-search').fill('Synthetic')
                            page.wait_for_function("trackSummaryStatus==='ready' && trackSummaryPage.tracks.length>1")
                            intended = page.evaluate('trackSummaryPage.tracks[0].handle')
                            page.locator('#tracks tbody tr').first.click()
                            page.wait_for_function("pendingSelectionOperation===null && document.getElementById('detail').getAttribute('aria-busy')==='false' && window.__dbBridge.detail_next_frame_ms!=null")
                            observed = page.evaluate('window.__dbBridge')
                            # Actual successful requests go through packaged handlers/repository.
                            posts = [r for r in observed['requests'] if r['method'] == 'POST' and r['route'] == '/api/current']
                            details = [r for r in observed['requests'] if r['route'] == '/api/tracks/<id>']
                            self.assertEqual(len(posts), 1)
                            self.assertEqual(len(details), 1)
                            self.assertEqual(posts[0]['request_handle'], intended)
                            self.assertEqual(posts[0]['response_handle'], intended)
                            self.assertEqual(details[0]['request_handle'], intended)
                            self.assertEqual(posts[0]['response_handle'], details[0]['response_handle'])
                            self.assertTrue(observed['is_trusted'])
                            self.assertEqual(observed['dom_handle'], details[0]['response_handle'])
                            self.assertTrue(page.locator('#detail').inner_text().strip())
                            self.assertLessEqual(posts[0]['parse_ms'], details[0]['request_ms'])
                            self.assertEqual(initial, 0)
                            actual = bridge_observation()
                            actual['fixture'] = fixture['manifest']
                            actual['cleanup'] = dict.fromkeys(('browser_closed', 'server_closed', 'scratch_removed'), False)
                            actual['unrelated_detail_requests'] = sum(r.get('request_handle') != intended for r in details)
                            self.assertEqual(observed['graph_counts'], fixture['manifest']['graph']['counts'])
                            # Compare decoded semantics: JS/Python float encoders differ.
                            self.assertEqual(observed['graph_value'], json.loads(fixture['graph_body']))
                            actual['initial_summary_requests'] = initial
                            graph_requests = [r for r in observed['requests'] if r['route'] == '/api/mood-axis-graph']
                            actual['graph_requests'] = len(graph_requests)
                            actual['graph_outcome'] = 'ok' if all(r['status'] == 200 for r in graph_requests) else 'http_error'
                            selected = actual['selections'][0]
                            for key in ('receipt_ms', 'loading_dom_ms', 'loading_frame_ms',
                                        'detail_dom_ready_ms', 'detail_next_frame_ms'):
                                selected[key] = observed.get(key)
                            for phase, record in (('post', posts[0]), ('detail', details[0])):
                                selected[phase] = {key: record[key] for key in
                                    ('request_id', 'request_ms', 'headers_ms', 'body_ms', 'parse_ms', 'status')}
                                selected[phase]['identity_matches'] = record['response_handle'] == intended
                            selected['loading_frame_was_busy'] = observed.get('loading_frame_was_busy')
                            selected['post']['accepted'] = posts[0]['status'] == 200 and posts[0]['response_handle'] == intended
                            for record in (posts[0], details[0]):
                                self.assertEqual(record['status'], 200)
                                ordered = [record[key] for key in ('request_ms', 'headers_ms', 'body_ms', 'parse_ms')]
                                self.assertEqual(ordered, sorted(ordered))
                            self.assertLessEqual(selected['detail']['parse_ms'], selected['detail_dom_ready_ms'])
                            self.assertLessEqual(selected['detail_dom_ready_ms'], selected['detail_next_frame_ms'])
                            # Hash the genuinely consumed graph, not the synthetic 41MiB profile.
                            actual['graph_consumed'] = {'sha256': observed['graph_sha256'],
                                                        'body_bytes': observed['graph_bytes']}
                            self.assertRegex(actual['graph_consumed']['sha256'], r'^[0-9a-f]{64}$')
                        finally:
                            browser.close()
                            browser_closed = True
                actual['cleanup']['browser_closed'] = browser_closed
                actual['cleanup']['server_closed'] = True
                actual['database_unchanged'] = before == fingerprint_sqlite_files(fixture['db_path'])
                self.assertTrue(actual['database_unchanged'])
            # Publication happens after actual browser/server/fixture ownership cleanup.
        self.assertFalse(Path(scratch).exists())
        actual['cleanup']['scratch_removed'] = True
        report = publish(actual)
        self.assertIn('detail_bridge', report['samples'][0],
                      'real writer/server/browser selected-detail evidence is discarded')
        self.assertEqual(report['samples'][0]['detail_bridge']['graph_consumed'], actual['graph_consumed'])
        self.assertNotIn('sha256:', json.dumps(report))


_DETAIL_PROBE = r"""(() => {
 const d=window.__dbBridge={requests:[]};const original=window.fetch;
 window.fetch=async function(input, options={}) {
  const path=new URL(String(input),location.href).pathname;
  const route=path.startsWith('/api/tracks/')&&path!='/api/tracks/summary'?'/api/tracks/<id>':path;
  const r={route,method:options.method||'GET',request_id:'request-'+(d.requests.length+1),request_ms:performance.now()};
  if(route==='/api/current'&&r.method==='POST')r.request_handle=JSON.parse(options.body).track_id;
  if(route==='/api/tracks/<id>')r.request_handle=decodeURIComponent(path.slice('/api/tracks/'.length));
  d.requests.push(r);const response=await original.apply(this,arguments);
  r.headers_ms=performance.now();r.status=response.status;
  response.json=async()=>{const text=await response.text();r.body_ms=performance.now();
   const value=JSON.parse(text);r.parse_ms=performance.now();
   if(route==='/api/current')r.response_handle=value.current_track_id;
   if(route==='/api/tracks/<id>')r.response_handle=value.handle;
   if(route==='/api/mood-axis-graph') {const bytes=new TextEncoder().encode(text);d.graph_bytes=bytes.length;
    d.graph_counts={nodes:value.nodes.length,links:value.links.length,unpositioned:value.unpositioned.length};
    d.graph_value=value;
    d.graph_sha256=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');}
   return value;};return response;
 };
 document.addEventListener('click',e=>{if(e.target.closest('#tracks tbody tr')){d.receipt_ms=performance.now();d.is_trusted=e.isTrusted;}},true);
})();"""

_WRAP_DETAIL = r"""() => {
 const d=window.__dbBridge, loading=renderDetailLoading, detail=renderDetail;
 renderDetailLoading=function(){const value=loading.apply(this,arguments);d.loading_dom_ms=performance.now();
  requestAnimationFrame(()=>{d.loading_frame_ms=performance.now();d.loading_frame_was_busy=document.getElementById('detail').getAttribute('aria-busy')==='true';});return value;};
 renderDetail=function(value){const result=detail.apply(this,arguments);d.dom_handle=value.handle;
  d.detail_dom_ready_ms=performance.now();requestAnimationFrame(()=>d.detail_next_frame_ms=performance.now());return result;};
}"""
