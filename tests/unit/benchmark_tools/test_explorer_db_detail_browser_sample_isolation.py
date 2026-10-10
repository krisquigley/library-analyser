"""Owned-server lifecycle contracts; mocks are not Chromium/browser evidence."""
from contextlib import contextmanager
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools.explorer_browser_diagnostic import collect_writer, failed_setup_attempt


class WriterSampleIsolationTests(unittest.TestCase):
    def collect_with_events(self, profile, launch_failure=False):
        events = []
        args = SimpleNamespace(track_count=12, seed=70, history_count=2,
                               allow_large=False, scenario='pending-then-ready',
                               graph_profile='small', observer_mode='verified',
                               samples=2, sample_profile=profile)
        driver = Mock()
        driver.chromium.launch.return_value.version = 'contract-only'
        driver.chromium.launch.return_value.new_page.return_value.evaluate.return_value = True
        if launch_failure:
            driver.chromium.launch.side_effect = [RuntimeError(), driver.chromium.launch.return_value]
        playwright = Mock()
        playwright.__enter__ = Mock(return_value=driver)
        playwright.__exit__ = Mock(return_value=False)

        @contextmanager
        def running_server(factory, path):
            events.append('server-enter')
            try:
                yield 'http://127.0.0.1:1'
            finally:
                events.append('server-exit')

        def observe(*args, **kwargs):
            events.append('observe')
            return failed_setup_attempt(TimeoutError())

        with patch('tools.explorer_http_diagnostic._running_server', running_server), \
             patch('tools.explorer_browser_diagnostic.observe_attempt', side_effect=observe):
            report = collect_writer(args, {'width': 1280, 'height': 720},
                                    Mock(return_value=playwright))
        return events, report, driver

    def test_server_is_owned_per_attempt_including_optional_warmup(self):
        for profile in ('process-cold', 'warm'):
            with self.subTest(profile=profile):
                events, report, driver = self.collect_with_events(profile)
                self.assertEqual(events, ['server-enter', 'observe', 'server-exit',
                                          'server-enter', 'observe', 'server-exit'])
                self.assertEqual(report['attempted'], 2)
                self.assertEqual(driver.chromium.launch.return_value.close.call_count, 2)
                self.assertEqual(report['warmup']['completed'], 2 if profile == 'warm' else 0)
                for sample in report['samples']:
                    self.assertTrue(all(sample['detail_bridge']['cleanup'].values()))
                    self.assertTrue(sample['detail_bridge']['database_unchanged'])

    def test_launch_failure_closes_its_server_before_next_attempt(self):
        events, report, driver = self.collect_with_events('process-cold', launch_failure=True)
        self.assertEqual(events, ['server-enter', 'server-exit',
                                  'server-enter', 'observe', 'server-exit'])
        self.assertEqual(report['attempted'], 2)
        driver.chromium.launch.return_value.close.assert_called_once()
        for sample in report['samples']:
            self.assertTrue(all(sample['detail_bridge']['cleanup'].values()))
