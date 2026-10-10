"""Tiny protocol/Node contracts; not real-browser responsiveness acceptance."""
import http.client
import json
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from threading import Event
import unittest
from urllib.parse import urlsplit

from tests.acceptance.test_explorer_browser_contention_observation import ControlledPage, Release
from tests.unit.benchmark_tools.test_explorer_browser_phase_attribution import _run_observer
from tools import explorer_browser_diagnostic as tool
from tools.explorer_browser_graph_fixture import public_browser_graph_fixture
from tools.explorer_browser_routes import public_routes


class BrowserContentionPlumbing(unittest.TestCase):
    def test_collected_native_mode_limitations_do_not_claim_hashing(self):
        args=SimpleNamespace(samples=0,graph_profile='small',allow_large=False,
                             scenario='pending-then-ready',observer_mode='native-json')
        api=SimpleNamespace(sync_playwright=MagicMock(return_value=MagicMock()))
        with patch.dict(sys.modules,{'playwright.sync_api':api}), patch.object(tool,'require_memory_bound'):
            report=tool.collect(args,{'width':800,'height':600})
        self.assertEqual(report['observer_mode'],'native-json')
        text=' '.join(report['limitations'])
        self.assertIn('Verified mode',text)
        self.assertIn('native-json uses native response.json',text)
        self.assertIn('consumed identity unavailable',text)
        self.assertNotIn('Consumed-body UTF-8 encoding and SHA256 hashing add bounded observer overhead.',text)

    def test_repeated_scene_and_model_preserve_first_consumption_spans(self):
        result=_run_observer('''
context.buildMoodGraphModel({});context.renderMap();advanceFrames(40);
context.buildMoodGraphModel({});context.renderMap();advanceFrames(80);
''')['diagnostic']['milestones_ms']
        self.assertEqual((result['graph_model_start'],result['graph_model_end']),(0,11))
        self.assertEqual((result['graph_scene_start'],result['graph_scene_end']),(11,24))
        self.assertEqual(result['graph_first_presentation'],40)

    def test_native_mode_and_probe_use_one_ordered_init_script(self):
        class Page(ControlledPage):
            def __init__(self,release):
                super().__init__(release);self.scripts=[]
            def add_init_script(self,script):self.scripts.append(script)
        release=Release([]);page=Page(release)
        tool.observe_attempt(page,'http://owned/',release,'pending-then-ready',observer_mode='native-json')
        self.assertEqual(len(page.scripts),1)
        self.assertTrue(page.scripts[0].startswith('window.__diagnosticObserverMode="native-json";'))
        self.assertIn('External observation',page.scripts[0])

    def test_superseding_focus_start_is_valid_for_contention_only(self):
        release=Release([]);page=ControlledPage(release)
        page.result['focus']['consumed_count']=2
        result=tool.observe_attempt(page,'http://owned/',release,'during-consumption')
        self.assertEqual(result['outcome'],'ok')
        self.assertEqual(result['focus']['consumed_count'],2)

    def test_reversed_or_missing_browser_receipt_is_not_success(self):
        attempt=tool.new_input_attempt('selection','body')
        for receipt in ({'action':'selection','is_trusted':True,'received_ms':20,'frame_ms':10},
                        {'action':'selection','is_trusted':True,'received_ms':None,'frame_ms':30},
                        {'action':'selection','is_trusted':False,'received_ms':20,'frame_ms':30}):
            with self.subTest(receipt=receipt):
                records=tool.merge_input_observations([attempt],[receipt],'ok')
                self.assertEqual(records[0]['outcome'],'invalid_response')

    def test_timeout_missing_receipt_cannot_retain_claimed_trust(self):
        attempt=tool.new_input_attempt('selection','body')
        receipt={'action':'selection','is_trusted':True,'received_ms':None,'frame_ms':30}
        record=tool.merge_input_observations([attempt],[receipt],'timeout')[0]
        self.assertEqual(record['outcome'],'timeout')
        self.assertIsNone(record['received_ms'])
        self.assertIsNone(record['frame_ms'])
        self.assertIsNone(record['is_trusted'])

    def test_lifecycle_success_does_not_claim_missing_contention_receipt_success(self):
        release=Release([]);page=ControlledPage(release)
        result=tool.observe_attempt(page,'http://owned/',release,'during-consumption')
        self.assertEqual(result['outcome'],'ok')
        self.assertEqual(result.get('contention_status'),'unavailable')
        self.assertEqual(result['input_observations'][0]['outcome'],'unavailable')

    def test_contention_routes_hold_body_and_allow_superseding_selection(self):
        fixture=public_browser_graph_fixture(profile='small',allow_large=False)
        with public_routes(fixture,'during-consumption') as (url,release):
            self.assertTrue(hasattr(release,'body_release'),'controlled body gate required')
            parts=urlsplit(url);connection=http.client.HTTPConnection(parts.hostname,parts.port,timeout=2)
            try:
                connection.request('GET','/api/tracks/summary');response=connection.getresponse()
                self.assertEqual(len(json.loads(response.read())['tracks']),2)
                release.set();connection.request('GET','/api/mood-axis-graph');response=connection.getresponse()
                first=response.read(1)
                self.assertEqual(first,fixture['encoded_body'][:1])
                self.assertFalse(release.body_release.is_set())
                release.body_release.set()
                self.assertEqual(first+response.read(),fixture['encoded_body'])
                connection.request('POST','/api/current',json.dumps({'track_id':'public-00001'}),{'Content-Type':'application/json'})
                response=connection.getresponse();self.assertEqual(response.status,200)
                self.assertEqual(json.loads(response.read())['current_track_id'],'public-00001')
            finally:
                connection.close()


if __name__=='__main__':unittest.main()
