"""PR73 regression: automatic graph HTTP failure is announced without focus theft.

Reuse the complete-script fake I/O harness, not replacement production functions.
The semantics are inspectable here; actual assistive-technology speech is not measured.
"""
import subprocess
import unittest

from tests.acceptance.test_explorer_auto_graph_independence import HARNESS, NODE, ROOT


class GraphFailureAnnouncementTests(unittest.TestCase):
    def test_automatic_http503_announces_error_without_moving_search_focus(self):
        self.assertTrue(NODE, 'Node is required; configure EXPLORER_TEST_NODE')
        scenario = r"""
(async()=>{
  // A minimal focus boundary: production focus calls would change activeElement.
  for(const root of Object.values(roots))
    root.focus=()=>{context.document.activeElement=root;};
  const createElement=context.document.createElement;
  context.document.createElement=tag=>{
    const node=createElement(tag);
    node.focus=()=>{context.document.activeElement=node;};
    return node;
  };
  await start();
  search.focus();
  assert.equal(context.document.activeElement,search);
  assert(walk(roots['graph-load-status']).some(n=>n.getAttribute('role')==='status'),
    'positive control: pending automatic graph already has status semantics');
  graphGate.resolve({ok:false,status:503,text:async()=>'graph temporarily unavailable'});
  await flush();
  assert(/Graph failed: graph temporarily unavailable/.test(graphStatus()),
    'HTTP503 exercises the real graph failure path');
  assert.equal(context.document.activeElement,search,'automatic failure must not move search focus');
  assertInlineOnly();
  const error=walk(roots['graph-load-status']).find(n=>
    /Graph failed: graph temporarily unavailable/.test(n.textContent));
  assert(error,'error text exists');
  assert(error.getAttribute('role')==='alert'||error.getAttribute('role')==='status'||
    ['polite','assertive'].includes(error.getAttribute('aria-live')),
    'automatic graph HTTP503 error text must have live announcement semantics');
  const retry=graphRetry();
  assert(retry,'failure keeps Retry graph');
  assert.equal(retry.tagName,'BUTTON','Retry remains a native control');
  assert.equal(retry.type,'button');
  assert.equal(retry.innerText.trim(),'Retry graph');
  assert.equal(retry.disabled,false);
  const retryGate=deferred();graphResponder=()=>retryGate.promise;
  const before=requests.length;retry.onclick();await flush();
  assert.deepEqual(requests.slice(before).map(r=>r.url.pathname),['/api/mood-axis-graph'],
    'Retry still requests only the graph');
  assert.equal(graphRequests().at(-1).url.searchParams.get('contract'),'v3');
  assert.equal(context.document.activeElement,search,'graph retry does not steal focus');
  assert(/Loading graph/.test(graphStatus()));
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
        for package in ('music_analyzer', 'music_explorer'):
            with self.subTest(package=package):
                app = ROOT / package / 'frameworks/explorer/assets/app.js'
                result = subprocess.run([NODE, '-e', HARNESS + scenario, str(app)],
                                        cwd=ROOT, capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
