"""Tiny outward composition contracts; mocks are not browser evidence."""
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch
import sys
import unittest

from tools.explorer_browser_diagnostic import collect, failed_setup_attempt, parser


class WriterBrowserCompositionTests(unittest.TestCase):
    def test_cli_accepts_explicit_writer_source_and_seed_history(self):
        args = parser().parse_args(['--fixture-source', 'writer-v10', '--track-count', '12',
                                   '--seed', '71', '--history-count', '3', '--output', '/tmp/report.json'])
        self.assertEqual((args.fixture_source, args.track_count, args.seed, args.history_count),
                         ('writer-v10', 12, 71, 3))

    def test_cli_accepts_writer_fault_scenarios(self):
        for scenario in ('rejected-post', 'detail-timeout'):
            args = parser().parse_args(['--fixture-source', 'writer-v10', '--scenario', scenario,
                                       '--output', '/tmp/report.json'])
            self.assertEqual(args.scenario, scenario)

    def test_failed_attempt_retains_exact_fixture_and_closed_ownership(self):
        args = SimpleNamespace(fixture_source='writer-v10', track_count=12, seed=70,
                               history_count=2, allow_large=False, graph_profile='small',
                               scenario='pending-then-ready', samples=1, observer_mode='verified')
        driver = Mock()
        browser = driver.chromium.launch.return_value
        browser.version = 'mock'
        browser.new_page.return_value.evaluate.return_value = True
        manager = Mock(__enter__=Mock(return_value=driver), __exit__=Mock(return_value=False))
        api = SimpleNamespace(sync_playwright=Mock(return_value=manager))
        with patch.dict(sys.modules, {'playwright.sync_api': api}), \
             patch('tools.explorer_browser_diagnostic.require_memory_bound'), \
             patch('tools.explorer_browser_diagnostic.observe_attempt',
                   return_value=failed_setup_attempt(TimeoutError())):
            report = collect(args, {'width': 1280, 'height': 720})
        self.assertEqual(report['scope'], 'public-synthetic-sqlite-browser')
        self.assertEqual(report['fixture']['schema_version'], 10)
        bridge = report['samples'][0]['detail_bridge']
        for key, value in bridge['fixture'].items():
            self.assertEqual(value, report['fixture'][key])
        self.assertIn('content_sha256', report['fixture'])
        self.assertIn('graph', report['fixture'])
        self.assertTrue(bridge['database_unchanged'])
        self.assertEqual(bridge['cleanup'], {'browser_closed': True, 'server_closed': True,
                                            'scratch_removed': True})
        self.assertEqual(report['samples'][0]['outcome'], 'timeout')
        self.assertEqual(report['server_observation']['status'], 'unavailable')
        self.assertEqual(report['server_observation']['sampling']['status'], 'complete')
        browser.close.assert_called_once()

    def test_validated_rejection_inventories_failure_and_retains_network_failures_once(self):
        args = SimpleNamespace(fixture_source='writer-v10', track_count=12, seed=70,
                               history_count=2, allow_large=False, graph_profile='small',
                               scenario='pending-then-ready', samples=1, observer_mode='verified')
        network = {'flow': 'graph', 'outcome': 'http_error'}
        rejected = {'flow': 'lifecycle', 'outcome': 'invalid_response'}
        timeout = {'flow': 'lifecycle', 'outcome': 'timeout'}
        from tests.acceptance.test_explorer_db_detail_browser_diagnostic import bridge_observation
        invalid_duration = {'flow': 'lifecycle', 'outcome': 'invalid_duration'}
        for initial, elapsed, outcome, failures, expected_outcome, expected in (
                (0, 12, 'ok', [], 'ok', []),
                (1, 12, 'ok', [], 'invalid_response', [rejected]),
                (1, 12, 'ok', [network, network], 'invalid_response', [network, network, rejected]),
                (1, 12, 'ok', [network, rejected], 'invalid_response', [network, rejected]),
                (0, 12, 'timeout', [network, timeout], 'timeout', [network, timeout]),
                (0, 13, 'ok', [network], 'invalid_duration', [network, invalid_duration]),
                (0, 13, 'ok', [invalid_duration], 'invalid_duration', [invalid_duration])):
            with self.subTest(initial=initial, elapsed=elapsed, outcome=outcome, failures=failures):
                bridge = bridge_observation()
                bridge['initial_summary_requests'] = initial
                sample = failed_setup_attempt(TimeoutError())
                sample.update(outcome=outcome, elapsed_ms=elapsed, failures=failures,
                              detail_bridge=bridge)
                driver = Mock()
                browser = driver.chromium.launch.return_value
                browser.version = 'mock'
                browser.new_page.return_value.evaluate.return_value = True
                manager = Mock(__enter__=Mock(return_value=driver),
                               __exit__=Mock(return_value=False))
                with patch.dict(sys.modules, {'playwright.sync_api': SimpleNamespace(
                        sync_playwright=Mock(return_value=manager))}), \
                     patch('tools.explorer_browser_diagnostic.require_memory_bound'), \
                     patch('tools.explorer_browser_diagnostic.observe_attempt', return_value=sample):
                    report = collect(args, {'width': 1280, 'height': 720})
                published = report['samples'][0]
                self.assertEqual(published['outcome'], expected_outcome)
                self.assertEqual(published['detail_bridge']['initial_summary_requests'], initial)
                self.assertEqual(published['failures'], expected)
                expected_counts = {}
                for failure in expected:
                    key = f"{failure['flow']}:{failure['outcome']}"
                    expected_counts[key] = expected_counts.get(key, 0) + 1
                self.assertEqual(report['failure_counts'], expected_counts)
                self.assertEqual(report['profiles']['process-cold']['failures'],
                                 {} if expected_outcome == 'ok' else {expected_outcome: 1})
                self.assertEqual(report['succeeded'], int(expected_outcome == 'ok'))
                self.assertEqual(sample['failures'], failures)

    def test_second_server_setup_failure_preserves_first_success_and_records_attempt(self):
        from music_explorer.frameworks.explorer.server import create_server
        from tests.acceptance.test_explorer_db_detail_browser_diagnostic import (
            bridge_observation, writer_args)
        args = writer_args()
        args.samples = 2
        successful = failed_setup_attempt(TimeoutError())
        successful.update(outcome='ok', elapsed_ms=12, failures=[],
                          detail_bridge=bridge_observation(), requests=[
                              {'route': '/api/mood-axis-graph', 'method': 'GET',
                               'status': 200, 'outcome': 'ok', 'elapsed_ms': 1}])
        driver = Mock()
        browser = driver.chromium.launch.return_value
        browser.version = 'mock'
        browser.new_page.return_value.evaluate.return_value = True
        manager = Mock(__enter__=Mock(return_value=driver), __exit__=Mock(return_value=False))
        calls = []

        def factory(*factory_args, **factory_kwargs):
            calls.append(True)
            if len(calls) == 2:
                raise OSError('secret bind/resource failure')
            return create_server(*factory_args, **factory_kwargs)

        with patch.dict(sys.modules, {'playwright.sync_api': SimpleNamespace(
                sync_playwright=Mock(return_value=manager))}), \
             patch('tools.explorer_browser_diagnostic.require_memory_bound'), \
             patch('music_explorer.frameworks.explorer.server.create_server', side_effect=factory), \
             patch('tools.explorer_browser_diagnostic.observe_attempt', return_value=successful):
            report = collect(args, {'width': 1280, 'height': 720})
        self.assertEqual(report['attempted'], 2)
        self.assertEqual(report['succeeded'], 1)
        first, second = report['samples']
        self.assertEqual(first['outcome'], 'ok')
        self.assertEqual(first['failures'], [])
        self.assertEqual(first['detail_bridge']['cleanup'], {
            'browser_closed': True, 'server_closed': True, 'scratch_removed': True})
        self.assertEqual(second['outcome'], 'invalid_response')
        self.assertEqual(second['failures'], [{'flow': 'lifecycle', 'outcome': 'invalid_response'}])
        self.assertEqual(second['detail_bridge']['cleanup'], {
            'browser_closed': True, 'server_closed': False, 'scratch_removed': True})
        self.assertTrue(all(s['detail_bridge']['database_unchanged'] for s in report['samples']))
        self.assertEqual(len(first['requests']), 1)
        self.assertEqual(second['requests'], [])
        self.assertEqual(report['failure_counts'], {'lifecycle:invalid_response': 1})
        browser.close.assert_called_once()
        self.assertNotIn('secret bind/resource failure', str(report))

    def test_warm_profile_primes_same_page_before_observation(self):
        args = SimpleNamespace(fixture_source='writer-v10', track_count=12, seed=70,
                               history_count=2, allow_large=False, graph_profile='small',
                               scenario='pending-then-ready', samples=1, observer_mode='verified',
                               sample_profile='warm', wait_timeout_ms=60000)
        driver = Mock()
        browser = driver.chromium.launch.return_value
        browser.version = 'mock'
        page = browser.new_page.return_value
        page.evaluate.return_value = True
        manager = Mock(__enter__=Mock(return_value=driver), __exit__=Mock(return_value=False))
        def observe(observed_page, url, release, scenario, mode):
            self.assertIs(observed_page, page)
            page.goto.assert_called_once_with(url, wait_until='domcontentloaded')
            page.wait_for_function.assert_called_once()
            page.set_default_timeout.assert_called_once_with(60000)
            self.assertEqual(release.writer_wait_timeout_ms, 60000)
            return failed_setup_attempt(TimeoutError())
        with patch.dict(sys.modules, {'playwright.sync_api': SimpleNamespace(
                sync_playwright=Mock(return_value=manager))}), \
             patch('tools.explorer_browser_diagnostic.require_memory_bound'), \
             patch('tools.explorer_browser_diagnostic.observe_attempt', side_effect=observe):
            report = collect(args, {'width': 1280, 'height': 720})
        self.assertEqual(report['samples'][0]['profile'], 'warm')
        self.assertEqual(report['warmup']['completed'], 1)
        self.assertEqual(report['safety_wait_timeout_ms'], 60000)
        browser.new_page.assert_called_once()

    def test_actual_merged_server_observer_records_requests_and_restores(self):
        from tools.explorer_http_diagnostic import _sample
        from music_explorer.infrastructure.explorer_readonly import ReadOnlyExplorerSQLiteRepository
        original = ReadOnlyExplorerSQLiteRepository.track_ids
        args = SimpleNamespace(fixture_source='writer-v10', track_count=12, seed=70,
                               history_count=2, allow_large=False, graph_profile='small',
                               scenario='pending-then-ready', samples=1, observer_mode='verified')
        driver = Mock()
        driver.chromium.launch.return_value.version = 'mock'
        driver.chromium.launch.return_value.new_page.return_value.evaluate.return_value = True
        manager = Mock(__enter__=Mock(return_value=driver), __exit__=Mock(return_value=False))
        def observe(page, url, release, scenario, mode):
            result = _sample(url, 5, [], [], 1)
            self.assertEqual(result['outcome'], 'ok')
            return failed_setup_attempt(TimeoutError())
        with patch.dict(sys.modules, {'playwright.sync_api': SimpleNamespace(
                sync_playwright=Mock(return_value=manager))}), \
             patch('tools.explorer_browser_diagnostic.require_memory_bound'), \
             patch('tools.explorer_browser_diagnostic.observe_attempt', side_effect=observe):
            report = collect(args, {'width': 1280, 'height': 720})
        self.assertIs(ReadOnlyExplorerSQLiteRepository.track_ids, original)
        server = report['server_observation']
        self.assertEqual(server['observer_mode'], 'observer_on')
        self.assertEqual(server['scope'], 'server-process-monotonic')
        self.assertTrue(any(span['phase'] == 'membership' and span['method'] == 'POST'
                            for span in server['spans']))
        self.assertTrue(any(span['phase'] == 'selected_read' and span['method'] == 'GET'
                            for span in server['spans']))
        self.assertIsNone(server['sequential_total_ms'])
        self.assertEqual(server['sampling']['status'], 'sampled')
        self.assertEqual(report['failure_counts'], {'lifecycle:timeout': 1})

    def test_launch_and_close_failures_retain_attempts_and_server_cleanup(self):
        args = SimpleNamespace(fixture_source='writer-v10', track_count=12, seed=70,
                               history_count=2, allow_large=False, graph_profile='small',
                               scenario='pending-then-ready', samples=1, observer_mode='verified')
        for failure in ('launch', 'close'):
            with self.subTest(failure=failure):
                driver = Mock()
                browser = driver.chromium.launch.return_value
                browser.version = 'mock'
                browser.new_page.return_value.evaluate.return_value = True
                if failure == 'launch':
                    driver.chromium.launch.side_effect = TimeoutError('secret path')
                else:
                    browser.close.side_effect = RuntimeError('secret path')
                manager = Mock(__enter__=Mock(return_value=driver), __exit__=Mock(return_value=False))
                with patch.dict(sys.modules, {'playwright.sync_api': SimpleNamespace(
                        sync_playwright=Mock(return_value=manager))}), \
                     patch('tools.explorer_browser_diagnostic.require_memory_bound'), \
                     patch('tools.explorer_browser_diagnostic.observe_attempt',
                           return_value=failed_setup_attempt(TimeoutError())):
                    report = collect(args, {'width': 1280, 'height': 720})
                self.assertEqual(report['attempted'], 1)
                self.assertEqual(report['succeeded'], 0)
                cleanup = report['samples'][0]['detail_bridge']['cleanup']
                self.assertTrue(cleanup['server_closed'])
                self.assertTrue(cleanup['scratch_removed'])
                self.assertEqual(cleanup['browser_closed'], failure == 'launch')
                self.assertNotIn('secret path', str(report))
