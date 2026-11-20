"""Issue70 PR3 graph/search independence contracts for both packaged scripts.

The complete delivery asset runs with fake browser I/O only. Baseline explicit-load
controls exercise the same graph fixture and canvas/detail adapters to distinguish
missing automatic startup REDs from broken fixtures. No private data or timing
claims; deferred responses cover request independence, not CPU responsiveness.
"""
from pathlib import Path
import subprocess
import unittest
from tests.support.explorer_app_bundle import explorer_app_script
from tests.support.explorer_graph_independence_harness import HARNESS, NODE, ROOT

if not NODE and Path('/tmp/node-host-v24').is_file():
    NODE = '/tmp/node-host-v24'


PENDING_SCENARIO = r"""
await start(mode);
assertInlineOnly();
assert(/loading graph/i.test(graphStatus()),'pending graph has inline loading feedback');
await searchAndDetail();
assert.equal(graphRequests().length,1,'search/detail must not restart pending graph');
await assertGraphCompletionPreservesSidebar();
"""

FAILURE_RETRY_SCENARIO = r"""
await start(mode);
await searchAndDetail();
graphGate.resolve(response('graph temporarily unavailable',false)); await flush();
assert(/graph temporarily unavailable/i.test(graphStatus()),'failed graph has scoped error feedback');
assertInlineOnly();
// Search and selection must still work after failure, not only while pending.
await searchAndDetail();
const retry=graphRetry(); assert(retry,'automatic graph failure offers an inline Retry graph button');
const beforeRows=rows()[0],beforeDetail=roots.detail.innerText;
const retryGate=deferred(); graphResponder=()=>retryGate.promise;
const before=requests.length; retry.onclick(); await flush();
const retried=requests.slice(before);
assert.equal(retried.length,1,'graph retry must not refresh state, search, or detail');
assert.equal(retried[0].url.pathname,'/api/mood-axis-graph');
assert.equal(retried[0].url.searchParams.get('contract'),'v3');
assert(/loading graph/i.test(graphStatus()),'retry replaces error with inline loading');
assert(!graphRetry(),'pending retry must not retain a clickable duplicate retry');
assertInlineOnly();
retryGate.resolve(response(graphBody)); await flush();
assert(/graph ready/i.test(graphStatus()));
assert(!graphRetry(),'successful retry clears error/retry');
assert(canvasPaints.length>0,'retry success renders real graph fixture');
assert.equal(rows()[0],beforeRows); assert.equal(roots.detail.innerText,beforeDetail);
assertInlineOnly();
"""

SEARCH_FAILURE_SCENARIO = r"""
await start(mode);
summaryResponder=()=>response('search temporarily unavailable',false);
await searchFor('Matching');
assert(/search temporarily unavailable/i.test(visibleStatus()),'fixture establishes visible search failure');
assert.equal(rows().length,0);
const failedSearchStatus=visibleStatus(),before=requests.length;
graphGate.resolve(response(graphBody)); await flush();
assert(/graph ready/i.test(graphStatus()),'search failure must not prevent independent graph success');
assert(canvasPaints.length>0,'graph response actually renders despite failed search');
assert.equal(graphRequests().length,1,'search failure must not restart graph');
assert.equal(requests.length,before,'graph completion must not refetch failed search or state');
assert.equal(visibleStatus(),failedSearchStatus,'graph success must not erase scoped search failure');
assert(retryButton(),'search retry remains usable after graph success');
summaryResponder=()=>response(page([fixtureTrack])); retryButton().onclick(); await flush();
assert.equal(rows().length,1,'search retry remains independent of ready graph');
assert.equal(graphRequests().length,1);
assertInlineOnly();
"""


class ExplorerAutomaticGraphIndependenceTests(unittest.TestCase):
    def run_browser(self, scenario, mode='automatic'):
        self.assertTrue(NODE, 'Node is required; configure EXPLORER_TEST_NODE')
        script = HARNESS + '\n(async()=>{\nconst mode=' + repr(mode) + ';\n' + scenario + '\n})().catch(e=>{console.error(e);process.exitCode=1;});'
        for package in ('music_analyzer', 'music_explorer'):
            with self.subTest(package=package):
                app = explorer_app_script(ROOT / package / 'frameworks/explorer/assets/app/main/main.js')
                result = subprocess.run([NODE, '-e', script, str(app)], cwd=ROOT,
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_search_and_selected_detail_work_through_pending_automatic_graph(self):
        self.run_browser(PENDING_SCENARIO)

    def test_search_detail_and_scoped_graph_retry_work_after_automatic_graph_failure(self):
        self.run_browser(FAILURE_RETRY_SCENARIO)

    def test_automatic_graph_renders_despite_failed_search_and_preserves_search_retry(self):
        self.run_browser(SEARCH_FAILURE_SCENARIO)

    def test_state_startup_failure_does_not_block_search_detail_or_successful_graph(self):
        """A distinct RED: existing startup state error leaves a blocking overlay."""
        self.run_browser(r"""
stateGate=deferred(); stateGate.resolve(response('state temporarily unavailable',false));
await start('baseline-control');
assert(/state temporarily unavailable/i.test(roots['loading-error'].innerText),
  'fixture establishes state startup failure rather than a graph failure');
await searchFor('Matching');
assert.equal(rows().length,1);
await selectResult();
graphGate.resolve(response(graphBody)); await flush();
assert(/graph ready/i.test(graphStatus()),'state failure must not prevent graph rendering');
assert(canvasPaints.length>0);
assertInlineOnly();
""")

if __name__ == '__main__':
    unittest.main()
