"""PR73 regression: automatic graph HTTP failure is announced without focus theft.

Reuse the complete-script fake I/O harness, not replacement production functions.
The semantics are inspectable here; actual assistive-technology speech is not measured.
"""
import subprocess
import unittest

from tests.acceptance.test_explorer_auto_graph_independence import HARNESS, NODE, ROOT


class GraphFailureAnnouncementTests(unittest.TestCase):
    def test_unchanged_state_refresh_preserves_ready_graph_and_m3u_controls(self):
        self.assertTrue(NODE, 'Node is required; configure EXPLORER_TEST_NODE')
        scenario = r"""
(async()=>{
  await start();
  graphGate.resolve(response(graphBody));await flush();
  assert(/Graph ready: 1 positioned tracks/.test(graphStatus()));
  const panel=roots['graph-load-status'];
  const children=[...panel.children];
  const m3u=context.document.getElementById('m3u-download-controls');
  const count=context.document.getElementById('m3u-count');
  assert(m3u&&count,'ready graph offers the actual M3U controls');
  const before=requests.length;
  stateGate=deferred();
  const refreshing=context.refresh();await flush();
  assert.deepEqual(requests.slice(before).map(r=>r.url.pathname),['/api/state']);
  stateGate.resolve(response(stateBody));await refreshing;await flush();
  assert.equal(graphRequests().length,1,'state refresh must not reload ready graph');
  assert.equal(panel.children.length,children.length);
  children.forEach((child,index)=>assert.equal(panel.children[index],child,
    'unchanged ready graph state refresh preserves every status subtree node'));
  assert.equal(context.document.getElementById('m3u-download-controls'),m3u);
  assert.equal(context.document.getElementById('m3u-count'),count);
  assertInlineOnly();
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
        for package in ('music_analyzer', 'music_explorer'):
            with self.subTest(package=package):
                app = ROOT / package / 'frameworks/explorer/assets/app.js'
                result = subprocess.run([NODE, '-e', HARNESS + scenario, str(app)],
                                        cwd=ROOT, capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_delayed_state_preserves_failed_graph_alert_and_focused_retry(self):
        self.assertTrue(NODE, 'Node is required; configure EXPLORER_TEST_NODE')
        scenario = r"""
(async()=>{
  // Model browser focus loss when a focused descendant is detached. Only fake
  // DOM I/O changes: the actual complete asset and startup functions run below.
  const instrument=node=>{
    node.focus=()=>{context.document.activeElement=node;};
    const replaceChildren=node.replaceChildren;
    node.replaceChildren=function(...children){
      const active=context.document.activeElement;
      if(active&&this.children.some(child=>walk(child).includes(active)))
        context.document.activeElement=null;
      return replaceChildren.call(this,...children);
    };
    return node;
  };
  Object.values(roots).forEach(instrument);
  const createElement=context.document.createElement;
  context.document.createElement=tag=>instrument(createElement(tag));
  stateGate=deferred();
  await start();
  assert.equal(requests.filter(r=>r.url.pathname==='/api/state').length,1,
    'startup state request is outstanding while graph runs independently');
  const mood=context.document.getElementById('selected-mood');
  const bpmMin=context.document.getElementById('bpm-min');
  mood.value='calm';mood.onchange();
  bpmMin.value='121';bpmMin.onchange();
  assert.equal(graphRequests().length,1,'pending mood/filter changes must not refetch graph');
  graphGate.resolve({ok:false,status:503,text:async()=>'graph temporarily unavailable'});
  await flush();
  const alert=walk(roots['graph-load-status']).find(n=>n.getAttribute('role')==='alert');
  assert(alert,'automatic HTTP503 creates a role=alert node');
  assert.match(alert.innerText,/Graph failed: graph temporarily unavailable/);
  const retry=graphRetry();
  assert(retry,'automatic HTTP503 offers Retry graph before state completes');
  assert.equal(retry.tagName,'BUTTON');
  assert.equal(retry.disabled,false);
  retry.focus();
  assert.equal(context.document.activeElement,retry);
  const before=requests.length;
  stateGate.resolve(response(stateBody));
  await flush();
  const currentAlert=walk(roots['graph-load-status']).find(n=>n.getAttribute('role')==='alert');
  const observed={sameAlert:currentAlert===alert,sameRetry:graphRetry()===retry,
    focusedRetry:context.document.activeElement===retry,graphRequests:graphRequests().length};
  console.log('delayed-state observations',JSON.stringify(observed));
  assert.equal(graphRequests().length,1,'state completion must not retry the failed graph');
  assert.equal(requests.length,before,'unchanged state completion must not initiate extra requests');
  assert.equal(currentAlert,alert,'unchanged delayed state must preserve the existing role=alert node');
  assert.equal(graphRetry(),retry,'unchanged delayed state must preserve the Retry graph DOM node');
  assert.equal(context.document.activeElement,retry,'unchanged delayed state must retain Retry graph focus');
  assertInlineOnly();
  // Exercise the preserved real handler, not a replacement production function.
  const retryGate=deferred();graphResponder=()=>retryGate.promise;
  retry.onclick();await flush();
  assert.deepEqual(requests.slice(before).map(r=>r.url.pathname),['/api/mood-axis-graph']);
  assert.equal(graphRequests().length,2,'explicit Retry issues exactly one graph request');
  assert.equal(graphRequests().at(-1).url.searchParams.get('contract'),'v3');
  assert.equal(graphRequests().at(-1).url.searchParams.get('mood'),'calm',
    'retry uses mood chosen while automatic graph was pending');
  assert.equal(bpmMin.value,'121','delayed state retains pending filter input');
  assert(/Loading graph/.test(graphStatus()));
  assert(!walk(roots['graph-load-status']).includes(alert),'real retry replaces failed alert');
  assert(!graphRetry(),'real retry removes stale Retry control');
  retryGate.resolve(response(graphBody));await flush();
  assert(/Graph ready: 0 positioned tracks/.test(graphStatus()),
    'successful retry applies preserved BPM filter to the 120 BPM fixture');
  assert.equal(canvasPaints.length,0,'filtered fixture must not paint a graph node');
  const readyStatus=roots['graph-load-status'].children[1];
  assert(graphButtons().some(n=>/Reload graph/.test(n.innerText)),
    'real success replaces loading with ready/reload controls');
  bpmMin.value='';bpmMin.onchange();await flush();
  assert(/Graph ready: 1 positioned tracks/.test(graphStatus()));
  assert(canvasPaints.length>0,'genuine filter change still renders the positioned fixture');
  assert(!walk(roots['graph-load-status']).includes(readyStatus),
    'genuine graph filter change refreshes status DOM');
  const failedAgain=deferred();graphResponder=()=>failedAgain.promise;
  graphButtons().find(n=>/Reload graph/.test(n.innerText)).onclick();await flush();
  assert(/Loading graph/.test(graphStatus()));
  failedAgain.resolve({ok:false,status:503,text:async()=>'second graph failure'});await flush();
  const nextAlert=walk(roots['graph-load-status']).find(n=>n.getAttribute('role')==='alert');
  assert(nextAlert&&nextAlert!==alert,'genuine new failure creates a fresh announced alert');
  assert.match(nextAlert.innerText,/second graph failure/);
  assert(graphRetry(),'genuine new failure restores Retry');
  assert.equal(graphRequests().length,3,'only explicit retry/reload add graph requests');
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
        for package in ('music_analyzer', 'music_explorer'):
            with self.subTest(package=package):
                app = ROOT / package / 'frameworks/explorer/assets/app.js'
                result = subprocess.run([NODE, '-e', HARNESS + scenario, str(app)],
                                        cwd=ROOT, capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

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
