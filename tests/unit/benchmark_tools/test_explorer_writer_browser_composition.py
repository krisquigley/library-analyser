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
