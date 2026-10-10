"""PR4d RED contracts for a future public-only real-browser diagnostic.

There is deliberately no implementation in this change. Default contracts are
small CLI and supplied-observation report checks (not browser evidence); they
launch no browser, server, or large fixture. Missing tool
is an assertion on subprocess output, never a module import/collection failure.

Real acceptance (not a passing skip or a fake-DOM performance baseline):
  RUN_EXPLORER_BROWSER_DIAGNOSTIC=1 python3 -m unittest -v \
    tests.acceptance.test_explorer_browser_diagnostic
Explicit expensive profile, in an externally resource-bounded environment:
  RUN_EXPLORER_BROWSER_DIAGNOSTIC=1 RUN_EXPLORER_BROWSER_DIAGNOSTIC_LARGE=1 \
    python3 -m unittest -v tests.acceptance.test_explorer_browser_diagnostic

The proposed tool serves actual packaged Explorer assets on an owned loopback
synthetic route server. Its public state/summary/current/detail responses must
use the generated graph's public IDs so selection focuses a real positioned
node. It owns Playwright Chromium and the browser-only graph from
public_browser_graph_fixture; it needs no writer fixture or SQLite database.
No user DB, remote target, audio, screenshots, HAR or response bodies are inputs
or publication artifacts. Graph bytes are not SQLite query-speed evidence.
No absolute latency budgets are asserted. Times are observations, not promises.
"""
import importlib.util
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest


MODULE = 'tools.explorer_browser_diagnostic'
ROOT = Path(__file__).resolve().parents[2]


def run_tool(arguments, scratch, timeout=20, script=None):
    """Hard kill and reap the entire owned process group, including on timeout."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', TMPDIR=str(scratch),
               TEMP=str(scratch), TMP=str(scratch),
               EXPLORER_DIAGNOSTIC_PRIVATE_SENTINEL='do-not-publish-env-secret-70')
    # Avoid publishing cwd/credentials or inheriting core-dump behavior.
    def child_limits():
        import resource
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        if timeout <= 20:  # CLI/report-policy children, never a real Chromium process
            resource.setrlimit(resource.RLIMIT_AS, (512 * 2**20, 512 * 2**20))
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(
            ([sys.executable, '-c', script] if script is not None else
             [sys.executable, '-m', MODULE, *arguments]), cwd=ROOT, env=env,
            stdout=stdout, stderr=stderr, start_new_session=True,
            preexec_fn=child_limits,
        )
        try:
            process.wait(timeout=timeout)
        finally:
            # Also reap descendants if the parent exited without cleaning up.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        stdout.seek(0)
        stderr.seek(0)
        return subprocess.CompletedProcess(process.args, process.returncode,
                                           stdout.read().decode('utf-8'),
                                           stderr.read().decode('utf-8'))


class _BrowserToolAssertions(unittest.TestCase):
    def assert_tool_present(self, result):
        self.assertNotIn(
            'No module named ' + MODULE, result.stderr,
            'Missing intended browser diagnostic tool; implement its public CLI. '
            'This is not a browser availability or fixture failure.',
        )
        self.assertNotIn('Traceback (most recent call last)', result.stderr)


class BrowserDiagnosticCLIContracts(_BrowserToolAssertions):
    def test_help_exposes_explicit_bounded_public_browser_invocation(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run_tool(['--help'], Path(directory))
        self.assert_tool_present(result)
        self.assertEqual(result.returncode, 0, result.stderr)
        for option in ('--real-browser', '--graph-profile', '--allow-large',
                       '--scenario', '--samples', '--viewport', '--output'):
            self.assertIn(option, result.stdout)
        for scenario in ('pending-then-ready', 'graph-failure-retry', 'search-failure'):
            self.assertIn(scenario, result.stdout)

    def test_browser_execution_requires_explicit_opt_in(self):
        with tempfile.TemporaryDirectory() as directory:
            scratch = Path(directory)
            report = scratch / 'report.json'
            result = run_tool(['--output', str(report)], scratch)
            self.assert_tool_present(result)
            self.assertEqual(result.returncode, 2)
            self.assertIn('--real-browser', result.stderr)
            self.assertFalse(report.exists(), 'refused execution must not emit evidence')

    def test_invalid_or_private_targets_are_rejected_before_browser_launch(self):
        # Parse-time failures: no Playwright/Chromium installation is needed.
        cases = [
            ['--samples', '0'], ['--samples', '101'],
            ['--viewport', '0x720'],
            ['--graph-profile', 'stress-41mib'],  # requires --allow-large
            ['--url', 'https://private.invalid/'],
            ['--db', '/private/library.sqlite'],
        ]
        with tempfile.TemporaryDirectory() as directory:
            scratch = Path(directory)
            for extra in cases:
                with self.subTest(arguments=extra):
                    report = scratch / 'report.json'
                    result = run_tool(['--real-browser', '--output', str(report),
                                       *extra], scratch)
                    self.assert_tool_present(result)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertFalse(report.exists())


class BrowserDiagnosticSuppliedReportContracts(_BrowserToolAssertions):
    """Pure report policy with fake inputs; emphatically NOT browser evidence."""
    def publish(self, expression):
        script = '''import importlib, json, sys
try:
    tool = importlib.import_module('tools.explorer_browser_diagnostic')
except ModuleNotFoundError as error:
    if error.name != 'tools.explorer_browser_diagnostic':
        raise
    print('No module named tools.explorer_browser_diagnostic', file=sys.stderr)
    sys.exit(1)
report = ''' + expression + '''
print(json.dumps(report, allow_nan=False, sort_keys=True))
'''
        with tempfile.TemporaryDirectory() as directory:
            result = run_tool([], Path(directory), script=script)
        self.assert_tool_present(result)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_supplied_failures_retained_excluded_from_success_percentiles(self):
        report = self.publish("""tool.publish_browser_report(attempts=[
            {'profile':'warm', 'outcome':'ok', 'elapsed_ms':12},
            {'profile':'warm', 'outcome':'timeout', 'elapsed_ms':999},
            {'profile':'warm', 'outcome':'ok', 'elapsed_ms':float('nan')},
            {'profile':'process-cold', 'outcome':'connection_error', 'elapsed_ms':None}
        ])""")
        self.assertEqual(report['browser_evidence'], 'supplied-observations-not-browser-acceptance')
        self.assertEqual(report['attempted'], 4)
        self.assertEqual(len(report['samples']), 4)
        warm = report['profiles']['warm']
        self.assertEqual(warm['succeeded'], 1)
        self.assertEqual(warm['failures'], {'timeout':1, 'invalid_duration':1})
        self.assertEqual(warm['p50_ms'], 12)
        self.assertEqual(warm['p95_ms'], 12)
        self.assertEqual(warm['max_ms'], 12)
        self.assertEqual(report['samples'][1]['elapsed_ms'], 999)
        self.assertEqual(report['samples'][2]['outcome'], 'invalid_duration')
        self.assertIsNone(report['samples'][2]['elapsed_ms'])
        cold = report['profiles']['process-cold']
        self.assertEqual(cold['succeeded'], 0)
        for field in ('p50_ms', 'p95_ms', 'max_ms'):
            self.assertIsNone(cold[field], 'all-failed is not zero milliseconds')

    def test_failed_missing_milestones_stay_null_and_reversed_intervals_are_flagged(self):
        report = self.publish("""tool.publish_browser_report(
            attempts=[{'profile':'warm', 'outcome':'timeout', 'elapsed_ms':30,
                       'milestones_ms':{'navigation':0, 'graph_headers':None,
                                        'graph_body':None, 'graph_json':None,
                                        'graph_model':None, 'graph_usable_render':None}}],
            intervals=[{'clock':'browser-performance', 'flow':'graph',
                        'phase':'body', 'start_ms':20, 'end_ms':10}]
        )""")
        sample = report['samples'][0]
        self.assertEqual(sample['outcome'], 'timeout')
        self.assertEqual(sample['milestones_ms']['navigation'], 0)
        for missing in ('graph_headers', 'graph_body', 'graph_json', 'graph_model',
                        'graph_usable_render'):
            self.assertIsNone(sample['milestones_ms'][missing])
        self.assertFalse(report['interval_validation']['valid'])
        self.assertTrue(report['interval_validation']['errors'])
        self.assertEqual(report['browser_evidence'], 'supplied-observations-not-browser-acceptance')

    def test_supplied_publication_redacts_targets_payloads_and_environment(self):
        report = self.publish("""tool.publish_browser_report(
            attempts=[{'profile':'private.invalid', 'outcome':'secret-error',
                       'elapsed_ms':1, 'body':'private-payload'}],
            requests=[{'method':'GET',
                       'url':'http://private.invalid/api/tracks/sha256:secret?token=secret',
                       'body':'private-payload', 'status':200, 'outcome':'ok',
                       'elapsed_ms':2, 'response_bytes':3}],
            environment={'hostname':'private.invalid', 'cwd':'/private/library',
                         'authorization':'secret-token', 'env':'private-env'}
        )""")
        self.assertEqual(report['browser_evidence'], 'supplied-observations-not-browser-acceptance')
        self.assertEqual(report['samples'][0]['profile'], 'unknown')
        self.assertEqual(report['samples'][0]['outcome'], 'unknown')
        self.assertEqual(report['requests'][0]['route'], '/api/tracks/<id>')
        text = json.dumps(report, allow_nan=False)
        for private in ('private.invalid', 'sha256:secret', 'token=secret',
                        'private-payload', '/private/library', 'secret-token', 'private-env'):
            self.assertNotIn(private, text)


@unittest.skipUnless(os.environ.get('RUN_EXPLORER_BROWSER_DIAGNOSTIC') == '1',
                     'explicit opt-in real Playwright Chromium diagnostic')
class RealBrowserDiagnosticAcceptance(_BrowserToolAssertions):
    @classmethod
    def setUpClass(cls):
        # Chromium reserves huge virtual address ranges; RLIMIT_AS is not a
        # credible browser RAM bound. Require externally owned cgroup hard RAM
        # limits and group OOM kill instead of silently launching unbounded.
        try:
            limit = int(Path('/sys/fs/cgroup/memory.max').read_text().strip())
            group_oom = Path('/sys/fs/cgroup/memory.oom.group').read_text().strip()
            bounded = 0 < limit <= 4 * 2**30 and group_oom == '1'
        except (OSError, ValueError):
            bounded = False
        if not bounded:
            raise AssertionError('Browser acceptance BLOCKED: require cgroup memory.max '
                                 '<=4GiB and memory.oom.group=1; not a RED baseline')
        if importlib.util.find_spec('playwright') is None:
            raise AssertionError('Browser acceptance BLOCKED: install Playwright and Chromium; '
                                 'missing browser is not a PR4d RED baseline')
        preflight = '''from playwright.sync_api import sync_playwright
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel='chromium', timeout=15000)
    try:
        page = browser.new_page()
        has_webgl = page.evaluate("""() => {
            const c = document.createElement('canvas');
            return !!(c.getContext('webgl2') || c.getContext('webgl'));
        }""")
        if not has_webgl:
            raise AssertionError('Chromium WebGL unavailable')
    finally:
        browser.close()
print('chromium-webgl-ready')
'''
        try:
            with tempfile.TemporaryDirectory() as directory:
                result = run_tool([], Path(directory), timeout=30, script=preflight)
            if result.returncode != 0 or result.stdout.strip() != 'chromium-webgl-ready':
                raise AssertionError('Chromium WebGL preflight rejected')
        except Exception as error:
            raise AssertionError('Browser acceptance BLOCKED: Chromium/WebGL preflight failed; '
                                 'not a PR4d RED baseline') from error

    def number(self, value):
        self.assertIn(type(value), (int, float))
        self.assertTrue(math.isfinite(value))
        self.assertGreaterEqual(value, 0)

    def collect(self, scenario, profile='small'):
        with tempfile.TemporaryDirectory() as directory:
            scratch = Path(directory)
            report_path = scratch / 'report.json'
            arguments = ['--real-browser', '--graph-profile', profile,
                         '--scenario', scenario, '--samples', '1',
                         '--viewport', '1280x720', '--output', str(report_path)]
            if profile != 'small':
                arguments.append('--allow-large')
            result = run_tool(arguments, scratch, timeout=180 if profile == 'small' else 600)
            self.assert_tool_present(result)
            self.assertEqual(result.returncode, 0, result.stderr)
            # Strict publication: reject NaN/Infinity instead of accepting Python extensions.
            def reject_constant(value):
                raise AssertionError('non-JSON numeric observation: ' + value)
            report = json.loads(report_path.read_text(), parse_constant=reject_constant)
            text = json.dumps(report, allow_nan=False)
            for forbidden in (directory, str(ROOT), os.path.expanduser('~'),
                              'http://', 'https://', 'sha256:', 'Traceback',
                              'decoded_body', 'encoded_body', 'authorization',
                              'do-not-publish-env-secret-70'):
                self.assertNotIn(forbidden.lower(), text.lower())
            # No crash dumps/HAR/screenshots/retained response files in owned scratch.
            self.assertEqual(sorted(p.name for p in scratch.iterdir()), ['report.json'])
            return report

    def assert_common(self, report, scenario, profile='small'):
        self.assertEqual(report['scope'], 'public-synthetic-browser-only')
        self.assertEqual(report['latency_budget_result'], 'not_asserted')
        self.assertEqual(report['scenario'], scenario)
        from tests.unit.benchmark_tools.test_explorer_browser_graph_fixture import SMALL, LARGE
        expected_nodes, expected_links, expected_bytes, expected_hash = (
            SMALL if profile == 'small' else LARGE)
        manifest = report['graph_fixture']
        self.assertEqual(manifest['source'], 'public-synthetic-browser-only')
        self.assertEqual(manifest['profile'], profile)
        self.assertEqual(manifest['seed'], 70)
        self.assertEqual(manifest['counts'], {'nodes': expected_nodes, 'links': expected_links,
                                             'unpositioned': 0})
        self.assertEqual(manifest['decoded'], {'body_bytes': expected_bytes,
                                              'sha256': expected_hash})
        self.assertEqual(manifest['content_encoding'], 'gzip')
        self.assertGreater(manifest['encoded']['body_bytes'], 0)
        self.assertRegex(manifest['encoded']['sha256'], r'^[0-9a-f]{64}$')
        self.assertEqual(report['environment']['browser']['engine'], 'chromium')
        self.assertEqual(report['environment']['browser']['driver'], 'playwright')
        self.assertTrue(report['environment']['browser']['version'])
        self.assertEqual(report['environment']['viewport'], {'width': 1280, 'height': 720})
        self.assertTrue(report['environment']['python_version'])
        self.assertTrue(report['environment']['platform'])
        rss = report['environment']['rss']
        self.assertIn(rss['status'], ('measured', 'unavailable'))
        if rss['status'] == 'measured':
            self.number(rss['peak_bytes'])
            self.assertIn(rss['scope'], ('browser-process-tree', 'diagnostic-process-tree'))
        else:
            self.assertIsNone(rss['peak_bytes'])
        self.assertEqual(len(report['samples']), 1)
        sample = report['samples'][0]
        self.assertEqual(sample['profile'], 'process-cold')  # fresh browser, not disk-cold
        self.assertEqual(sample['clock'], 'browser-performance')
        self.assertEqual(sample['ui_source'], 'packaged-explorer-assets')
        self.assertEqual(sample['browser_evidence'], 'real-playwright-chromium')
        self.assertTrue(sample['webgl'])
        for field in ('frame_gaps_ms', 'long_tasks_ms'):
            observations = sample['responsiveness'][field]
            self.assertIsInstance(observations, list)
            for observation in observations:
                self.number(observation)
        self.assertGreater(sample['responsiveness']['frame_count'], 0)
        self.assertEqual(sample['responsiveness']['long_tasks_status'], 'observed')
        for value in sample['responsiveness']['input_latency_ms']:
            self.number(value)
        self.assertTrue(sample['responsiveness']['input_latency_ms'])
        for request in sample['requests']:
            self.assertNotIn('url', request)
            self.assertNotIn('body', request)
            self.assertIn(request['route'], ('/api/state', '/api/mood-axis-graph',
                          '/api/tracks/summary', '/api/current', '/api/tracks/<id>',
                          'asset', 'unknown'))
            self.assertIn(request['outcome'], ('ok', 'http_error', 'timeout',
                                             'connection_error', 'invalid_response'))
        requests = sample['requests']
        summaries = [r for r in requests if r['route'] == '/api/tracks/summary']
        self.assertEqual(sample['initial_sidebar_requests'], 0)
        self.assertTrue(summaries)
        self.assertEqual(sum(r['route'] == '/api/tracks/<id>' for r in requests), 1)
        self.assertEqual(sum(r['route'] == '/api/current' for r in requests), 1)
        self.assertTrue(sample['selection']['accepted'])
        return sample

    def assert_ready_lifecycle(self, sample):
        milestones = sample['milestones_ms']
        ordered = ('navigation', 'graph_request', 'graph_headers', 'graph_body',
                   'graph_json', 'graph_model', 'graph_usable_render')
        for key in ordered:
            self.number(milestones[key])
        self.assertEqual(milestones['navigation'], 0)
        self.assertEqual([milestones[key] for key in ordered],
                         sorted(milestones[key] for key in ordered))
        for key in ('search_usable', 'search_input', 'search_rows', 'selection_intent',
                    'selection_feedback', 'detail_painted', 'focus_start', 'focus_end'):
            self.number(milestones[key])
        self.assertLessEqual(milestones['search_input'], milestones['search_rows'])
        self.assertLessEqual(milestones['search_rows'], milestones['selection_intent'])
        self.assertLessEqual(milestones['selection_intent'], milestones['selection_feedback'])
        self.assertLessEqual(milestones['selection_feedback'], milestones['detail_painted'])
        self.assertLess(milestones['detail_painted'], milestones['graph_body'],
                        'real search/detail must work while graph response is held pending')
        self.assertLessEqual(milestones['graph_model'], milestones['focus_start'])
        self.assertLess(milestones['focus_start'], milestones['focus_end'])
        self.assertTrue(sample['render']['canvas_visible'])
        self.assertTrue(sample['render']['nonempty_pixels'])
        self.assertTrue(sample['render']['positioned_nodes_visible'])
        self.assertTrue(sample['focus']['selected_node_in_view'])
        self.assertTrue(sample['focus']['halo_visible'])
        self.assertTrue(sample['focus']['finite_camera'])
        self.assertEqual(sample['focus']['consumed_count'], 1)

    def test_pending_graph_allows_search_detail_then_real_render_and_focus(self):
        report = self.collect('pending-then-ready')
        sample = self.assert_common(report, 'pending-then-ready')
        self.assert_ready_lifecycle(sample)
        self.assertEqual(sample['failures'], [])
        self.assertEqual(report['attempted'], 1)
        self.assertEqual(report['succeeded'], 1)

    def test_graph_failure_is_retained_and_retry_does_not_block_selection(self):
        report = self.collect('graph-failure-retry')
        sample = self.assert_common(report, 'graph-failure-retry')
        self.assert_ready_lifecycle(sample)
        self.assertTrue(sample['graph_error_visible'])
        self.assertEqual(sample['graph_retry_count'], 1)
        graph_requests = [r for r in sample['requests'] if r['route'] == '/api/mood-axis-graph']
        self.assertEqual(len(graph_requests), 2)
        self.assertEqual([r['outcome'] for r in graph_requests], ['http_error', 'ok'])
        self.assertEqual(sample['failures'], [{'flow': 'graph', 'outcome': 'http_error'}])
        self.assertEqual(report['failure_counts'], {'graph:http_error': 1})

    def test_search_failure_is_retained_without_preventing_graph_render(self):
        report = self.collect('search-failure')
        sample = self.assert_common(report, 'search-failure')
        self.assert_ready_lifecycle(sample)
        self.assertTrue(sample['search_error_visible'])
        self.assertEqual(sample['search_retry_count'], 1)
        summaries = [r for r in sample['requests'] if r['route'] == '/api/tracks/summary']
        self.assertEqual([r['outcome'] for r in summaries], ['http_error', 'ok'])
        self.assertEqual(sample['failures'], [{'flow': 'search', 'outcome': 'http_error'}])
        self.assertEqual(report['failure_counts'], {'search:http_error': 1})

    @unittest.skipUnless(os.environ.get('RUN_EXPLORER_BROWSER_DIAGNOSTIC_LARGE') == '1',
                         'explicit opt-in ~41 MiB browser-only graph; not server speed')
    def test_stress_profile_records_real_browser_lifecycle_without_latency_budget(self):
        report = self.collect('pending-then-ready', 'stress-41mib')
        sample = self.assert_common(report, 'pending-then-ready', 'stress-41mib')
        self.assert_ready_lifecycle(sample)
        self.assertEqual(report['graph_fixture']['decoded']['body_bytes'], 41 * 2**20)
        self.assertEqual(report['graph_fixture']['counts']['nodes'], 20000)
        self.assertEqual(report['graph_fixture']['counts']['links'], 19999)


if __name__ == '__main__':
    unittest.main()
