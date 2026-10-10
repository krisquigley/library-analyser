"""Setup failures retain completed samples without publishing exception details."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import tempfile
import json
import unittest
from unittest.mock import Mock, patch
import sys

from tools import explorer_browser_diagnostic as tool


class BrowserSetupRetention(unittest.TestCase):
    def collect_with_failure(self, stage, via_main=False):
        secret = 'private /home/catalogue token=secret'
        browsers = [Mock(version='public-version'), Mock(version='public-version')]
        for browser in browsers:
            browser.new_page.return_value.evaluate.return_value = True
        chromium = Mock()
        chromium.launch.side_effect = browsers
        if stage == 'launch':
            chromium.launch.side_effect = [browsers[0], RuntimeError(secret)]
        elif stage == 'new_page':
            browsers[1].new_page.side_effect = RuntimeError(secret)
        elif stage == 'webgl_exception':
            browsers[1].new_page.return_value.evaluate.side_effect = RuntimeError(secret)
        elif stage == 'webgl_missing':
            browsers[1].new_page.return_value.evaluate.return_value = False
        elif stage == 'launch_timeout':
            timeout = type('TimeoutError', (Exception,), {})
            chromium.launch.side_effect = [browsers[0], timeout(secret)]
        driver = Mock(chromium=chromium)
        playwright = Mock()
        playwright.__enter__ = Mock(return_value=driver)
        playwright.__exit__ = Mock(return_value=False)
        api = SimpleNamespace(sync_playwright=Mock(return_value=playwright))
        fixture = {'manifest': {'public': 'fixture'}}
        completed = {'outcome': 'ok', 'failures': [], 'milestones_ms': {'navigation': 0}}
        route_exits = []

        @contextmanager
        def routes(*args):
            try:
                yield 'http://owned.invalid', Mock()
            finally:
                route_exits.append(True)

        args = SimpleNamespace(samples=2, graph_profile='small', allow_large=False,
                               scenario='pending-then-ready')
        with patch.dict(sys.modules, {'playwright.sync_api': api}), \
             patch.object(tool, 'require_memory_bound'), \
             patch('tools.explorer_browser_graph_fixture.public_browser_graph_fixture', return_value=fixture), \
             patch.object(tool, 'public_routes', routes), \
             patch.object(tool, 'observe_attempt', return_value=completed) as observe, \
             patch.object(tool, 'validate_graph_response'), \
             patch.object(tool.tempfile, 'TemporaryDirectory', wraps=tempfile.TemporaryDirectory) as scratch:
            if via_main:
                # Exercise the real CLI publication boundary, not a mocked collect.
                with tempfile.TemporaryDirectory(prefix='setup-report-') as output_dir:
                    args.real_browser = True
                    args.viewport = '800x600'
                    args.output = Path(output_dir) / 'report.json'
                    cli = Mock()
                    cli.parse_args.return_value = args
                    with patch.object(tool, 'parser', return_value=cli):
                        tool.main()
                    cli.exit.assert_not_called()
                    self.assertTrue(args.output.is_file())
                    report = json.loads(args.output.read_text())
            else:
                report = tool.collect(args, {'width': 800, 'height': 600})
        self.assertEqual(report['attempted'], 2)
        self.assertEqual(report['succeeded'], 1)
        if via_main:
            self.assertEqual(report['samples'][0], completed)
        else:
            self.assertIs(report['samples'][0], completed)
        failure = report['samples'][1]
        outcome = 'timeout' if stage == 'launch_timeout' else 'invalid_response'
        self.assertEqual(failure['outcome'], outcome)
        self.assertEqual(failure['failures'], [{'flow': 'lifecycle', 'outcome': outcome}])
        self.assertEqual(report['failure_counts'], {f'lifecycle:{outcome}': 1})
        self.assertEqual(failure['milestones_ms'], dict.fromkeys(tool.MILESTONES))
        self.assertIsNone(failure['elapsed_ms'])
        self.assertEqual(failure['requests'], [])
        self.assertEqual(failure['browser_evidence'], 'real-playwright-chromium')
        self.assertNotIn('private', str(report))
        self.assertNotIn('secret', str(report))
        self.assertEqual(observe.call_count, 1)
        self.assertEqual(len(route_exits), 2)
        browsers[0].close.assert_called_once_with()
        if stage.startswith('launch'):
            browsers[1].close.assert_not_called()
        else:
            browsers[1].close.assert_called_once_with()
        self.assertEqual(playwright.__exit__.call_count, 1)
        scratch_path = Path(chromium.launch.call_args_list[0].kwargs['env']['XDG_CONFIG_HOME']).parent
        self.assertFalse(scratch_path.exists())
        return report

    def test_main_writes_report_after_second_setup_failure(self):
        for stage in ('launch', 'launch_timeout', 'new_page', 'webgl_exception', 'webgl_missing'):
            with self.subTest(stage=stage):
                self.collect_with_failure(stage, via_main=True)

    def test_second_launch_failure_retains_first_sample(self):
        self.collect_with_failure('launch')

    def test_second_launch_timeout_retains_first_sample(self):
        self.collect_with_failure('launch_timeout')

    def test_second_new_page_failure_retains_first_sample(self):
        self.collect_with_failure('new_page')

    def test_second_webgl_exception_retains_first_sample(self):
        self.collect_with_failure('webgl_exception')

    def test_second_webgl_missing_retains_first_sample(self):
        self.collect_with_failure('webgl_missing')
