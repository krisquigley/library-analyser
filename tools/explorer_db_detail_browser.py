"""Outward observation of public writer fixtures through packaged Explorer.

Only transient page observations contain handles or decoded graph bodies. Public
samples correlate identities into booleans before crossing the report boundary.
Observer text/parse/hash work perturbs timing; next-frame is not physical paint.
"""
import json
from pathlib import Path

PROBE = Path(__file__).with_name('explorer_db_detail_probe.js')
PHASES = ('request_id', 'request_ms', 'headers_ms', 'body_ms', 'parse_ms', 'status')
SELECTION_TIMES = ('receipt_ms', 'loading_dom_ms', 'loading_frame_ms',
                   'detail_dom_ready_ms', 'detail_next_frame_ms')
# Inspect actual structure in-page. DOM text/node references stay transient;
# request/DTO identity is a separate observation, never a DOM identity claim.
DETAIL_RENDERED = """(intended, before, previous, previousText, previousHandle) => {
  const root=document.getElementById('detail');
  const rows=document.querySelectorAll('#tracks tbody tr.current');
  const visible=el=>{
    if(!el||!el.checkVisibility({checkOpacity:true,checkVisibilityCSS:true}))return false;
    const box=el.getBoundingClientRect();
    return box.width>0&&box.height>0&&box.right>0&&box.bottom>0&&box.left<innerWidth&&box.top<innerHeight;
  };
  if(!visible(root)||root.getAttribute('aria-busy')!=='false'||rows.length!==1||
     !intended||rows[0].dataset.trackId!==intended)return false;
  const heading=root.children[0], fields=root.children[1];
  if(root.children.length!==2||heading?.tagName!=='H3'||heading.textContent!=='Current Track'||
     fields?.tagName!=='DIV'||!visible(heading)||!visible(fields)||fields===before||fields===previous)return false;
  const metadata=fields.children[0];
  if(!metadata?.matches('section.field.track-metadata')||!visible(metadata)||
     !Array.from(fields.children).every(el=>el.matches('section.field'))||root.querySelector('[role="alert"]'))return false;
  // A new node containing the previous track's identical presentation is stale,
  // not evidence of a new selection. This comparison remains entirely in-page.
  return !(previousHandle&&previousHandle!==intended&&fields.textContent===previousText);
}"""
WRAP_DETAIL = """() => {
 const presented=(""" + DETAIL_RENDERED + """), d=window.__dbBridge,
  loading=renderDetailLoading, detail=renderDetail;
 let previous=null, previousText=null, previousHandle=null;
 renderDetailLoading=function(){const result=loading.apply(this,arguments), s=d.selections.at(-1);
  if(s&&s.loading_dom_ms==null){s.loading_dom_ms=performance.now();requestAnimationFrame(()=>{
   s.loading_frame_ms=performance.now();s.loading_frame_was_busy=document.getElementById('detail').getAttribute('aria-busy')==='true';});}return result;};
 renderDetail=function(){const root=document.getElementById('detail'), before=root.children[1],
  result=detail.apply(this,arguments), s=d.selections.at(-1), ready=performance.now(), fields=root.children[1];
  if(s){requestAnimationFrame(()=>{
   const contentMatches=window.__dbDetailContentMatches(s.sequence,fields);
   const structurePresented=presented(s.intended_handle,before,previous,previousText,previousHandle);
   s.detail_presented=contentMatches&&structurePresented;
   s.dom_identity_matches=null;
   s.detail_dom_ready_ms=s.detail_presented?ready:null;s.detail_next_frame_ms=performance.now();
   // Keep structural history even after a content mismatch, so a later clone
   // cannot evade the existing conservative equal-content exclusion.
   if(structurePresented){previous=fields;previousText=fields.textContent;previousHandle=s.intended_handle;}
  });}return result;};
}"""


def bridge_observation(raw, fixture):
    """Correlate actual request, response and DOM identities without retaining them."""
    requests = raw.get('requests', [])
    selections = []
    related = set()
    for observed in raw.get('selections', []):
        sequence = observed['sequence']
        intended = observed.get('intended_handle')
        selected = {'sequence': sequence, 'clock': 'browser-performance',
                    'is_trusted': observed.get('is_trusted'),
                    **{key: observed.get(key) for key in SELECTION_TIMES},
                    'loading_frame_was_busy': observed.get('loading_frame_was_busy'),
                    'detail_presented': observed.get('detail_presented'),
                    'dom_identity_matches': None}
        for phase, route in (('post', '/api/current'), ('detail', '/api/tracks/<id>')):
            matches = [(index, record) for index, record in enumerate(requests)
                       if record.get('sequence') == sequence and record.get('route') == route
                       and (phase != 'post' or record.get('method') == 'POST')]
            selected[phase] = None
            if not matches:
                continue
            index, record = matches[0]
            safe = {key: record.get(key) for key in PHASES}
            response = record.get('response_handle')
            identity = (bool(intended) and record.get('request_handle') == intended
                        and response == intended and len(matches) == 1)
            safe['identity_matches'] = identity if response is not None else None
            if phase == 'post':
                if record.get('status') is not None and record['status'] >= 400:
                    safe['accepted'] = False
                elif response is None:
                    safe['accepted'] = None
                else:
                    safe['accepted'] = (record.get('status') == 200 and identity
                                        and observed.get('is_trusted') is True)
            else:
                # This is request/response identity only, never DOM identity.
                safe['identity_matches'] = identity if response is not None else None
                if record.get('request_handle') == intended:
                    related.add(index)
            selected[phase] = safe
        selections.append(selected)
    graphs = [record for record in requests if record.get('route') == '/api/mood-axis-graph']
    graph_outcome = ('ok' if graphs and graphs[-1].get('status') == 200 else
                     'http_error' if graphs and graphs[-1].get('status') is not None else 'unavailable')
    bridge = {'fixture': fixture['manifest'], 'server': 'packaged-explorer-loopback',
              'initial_summary_requests': raw.get('initial_summary_requests'),
              'unrelated_detail_requests': sum(index not in related for index, record in enumerate(requests)
                                                if record.get('route') == '/api/tracks/<id>'),
              'graph_requests': len(graphs), 'graph_outcome': graph_outcome,
              'graph_retry_count': raw.get('graph_retry_count', 0),
              'graph_attempt_outcomes': ['ok' if record.get('status') == 200 else
                                         'http_error' if record.get('status') is not None else 'unavailable'
                                         for record in graphs],
              'latest_selection_sequence': selections[-1]['sequence'] if selections else None,
              'server_phases': {'status': 'unavailable', 'clock': None, 'spans': None},
              'selections': selections}
    if raw.get('graph_sha256') is not None:
        bridge['graph_consumed'] = {'sha256': raw['graph_sha256'], 'body_bytes': raw.get('graph_bytes')}
        bridge['graph_matches_fixture'] = (raw.get('graph_value') == json.loads(fixture['graph_body'])
                                            and raw.get('graph_counts') == fixture['manifest']['graph']['counts'])
    return bridge


def _webgl_context(source):
    source = source if isinstance(source, dict) else {}
    labels = {'api_version': ('webgl1', 'webgl2'), 'vendor': ('WebKit', 'unclassified'),
              'renderer': ('WebKit WebGL', 'unclassified'),
              'implementation': ('software-swiftshader', 'software-other', 'unclassified')}
    return {key: source.get(key) if source.get(key) in allowed else None
            for key, allowed in labels.items()}


def _request_outcome(record, scenario, fault_injected):
    status = record.get('status')
    if status is not None:
        return 'ok' if 200 <= status < 300 else 'http_error'
    if not record.get('failed'):
        return 'unknown'
    if scenario == 'detail-timeout' and fault_injected and record.get('route') == '/api/tracks/<id>':
        return 'timeout'
    return 'connection_error'


def _select(page, index):
    intended = page.evaluate(f'trackSummaryPage.tracks[{index}].handle')
    page.evaluate('(handle)=>window.__dbBridge.intended_handle=handle', intended)
    sequence = page.evaluate('window.__dbBridge.selections.length+1')
    page.locator('#tracks tbody tr').nth(index).click()
    page.wait_for_function("sequence => pendingSelectionOperation===null && "
                           "document.getElementById('detail').getAttribute('aria-busy')==='false' && "
                           "(window.__dbBridge.selections.find(s=>s.sequence===sequence)?.detail_next_frame_ms!=null || "
                           "window.__dbBridge.requests.some(r=>r.sequence===sequence && r.method==='POST' && r.status>=400))",
                           arg=sequence)


def observe_writer_attempt(page, url, scenario, observer_mode, fixture, wait_timeout_ms=10000):
    """Drive trusted search-row input on real assets; retain failures and partials."""
    supported = ('pending-then-ready', 'latest-selection', 'graph-failure-retry',
                 'search-failure', 'rejected-post', 'detail-timeout')
    if (scenario not in supported or observer_mode != 'verified'
            or type(wait_timeout_ms) is not int or not 10000 <= wait_timeout_ms <= 120000):
        return {'profile': 'process-cold', 'clock': 'browser-performance',
                'ui_source': 'packaged-explorer-assets', 'browser_evidence': 'real-playwright-chromium',
                'observer_mode': observer_mode, 'outcome': 'invalid_response', 'elapsed_ms': None,
                'detail_bridge': bridge_observation({}, fixture), 'requests': [],
                'failures': [{'flow': 'lifecycle', 'outcome': 'invalid_response'}]}
    outcome = 'ok'
    faults = []
    # Faults are explicit browser adapter injection; successful requests still
    # go through the real packaged server. Do not label these server failures.
    def fail_once(route):
        faults.append(route.request.url.split('/api/')[-1].split('?')[0])
        if scenario == 'detail-timeout':
            route.abort('timedout')
        else:
            route.fulfill(status=409 if scenario == 'rejected-post' else 503,
                          content_type='application/json', body='{}')
    try:
        page.set_default_timeout(wait_timeout_ms)
        page.add_init_script(PROBE.read_text())
        if scenario == 'graph-failure-retry':
            page.route('**/api/mood-axis-graph*', fail_once, times=1)
        if scenario == 'search-failure':
            page.route('**/api/tracks/summary?*', fail_once, times=1)
        if scenario == 'rejected-post':
            page.route('**/api/current', fail_once, times=1)
        if scenario == 'detail-timeout':
            page.route('**/api/tracks/sha256*', fail_once, times=1)
        page.goto(url, wait_until='domcontentloaded')
        page.wait_for_function("state.selection_epoch!=null && typeof renderDetail==='function'")
        page.evaluate("window.__dbBridge.initial_summary_requests=window.__dbBridge.requests.filter(r=>r.route==='/api/tracks/summary').length")
        page.evaluate(WRAP_DETAIL)
        page.locator('#track-search').fill('Synthetic')
        if scenario == 'search-failure':
            page.wait_for_function("trackSummaryStatus==='error'")
            page.get_by_role('button', name='Retry search').click()
        page.wait_for_function("trackSummaryStatus==='ready' && trackSummaryPage.tracks.length>1")
        _select(page, 0)
        if scenario == 'rejected-post':
            raise RuntimeError('classified injected rejection')
        if scenario in ('latest-selection', 'graph-failure-retry'):
            _select(page, 1)
        if scenario == 'graph-failure-retry':
            page.wait_for_function("graphLoadState.status==='error'")
            page.get_by_role('button', name='Retry graph').click()
            page.evaluate('window.__dbBridge.graph_retry_count=1')
        page.wait_for_function("graphLoadState.status==='ready' && forceGraph && "
                               "window.__dbBridge.graph_sha256!=null")
        page.evaluate("""() => {
          const gl=forceGraph.renderer().getContext(), d=window.__dbBridge;
          const debug=gl.getExtension('WEBGL_debug_renderer_info');
          const implementation=debug?String(gl.getParameter(debug.UNMASKED_RENDERER_WEBGL)).toLowerCase():'';
          d.webgl_context={api_version:gl instanceof WebGL2RenderingContext?'webgl2':'webgl1',
            vendor:gl.getParameter(gl.VENDOR)==='WebKit'?'WebKit':'unclassified',
            renderer:gl.getParameter(gl.RENDERER)==='WebKit WebGL'?'WebKit WebGL':'unclassified',
            implementation:implementation.includes('swiftshader')?'software-swiftshader':
             (implementation.includes('llvmpipe')||implementation.includes('softpipe'))?'software-other':'unclassified'};
          return new Promise(resolve=>requestAnimationFrame(()=>resolve()));
        }""")
    except Exception as error:
        outcome = 'timeout' if type(error).__name__ == 'TimeoutError' else 'invalid_response'
    try:
        raw = page.evaluate('window.__dbBridge') or {}
    except Exception:
        raw = {}
    bridge = bridge_observation(raw, fixture)
    if bridge.get('graph_matches_fixture') is False:
        outcome = 'invalid_response'
    selected = bridge['selections'][-1] if bridge['selections'] else {}
    if outcome == 'ok' and (not selected.get('detail') or
                            selected['detail'].get('identity_matches') is not True
                            or selected.get('detail_presented') is not True):
        outcome = 'invalid_response'
    elapsed = (selected['detail_next_frame_ms'] - selected['receipt_ms']
               if outcome == 'ok' and selected.get('detail_next_frame_ms') is not None else None)
    failures = [{'flow': 'lifecycle', 'outcome': outcome}] if outcome != 'ok' else []
    for request in raw.get('requests', []):
        request_outcome = _request_outcome(request, scenario, bool(faults))
        if request_outcome in ('http_error', 'timeout', 'connection_error'):
            flow = ('graph' if request['route'] == '/api/mood-axis-graph' else
                    'search' if request['route'] == '/api/tracks/summary' else 'selection')
            failures.append({'flow': flow, 'outcome': request_outcome})
    return {'profile': 'process-cold', 'clock': 'browser-performance',
            'ui_source': 'packaged-explorer-assets', 'browser_evidence': 'real-playwright-chromium',
            'observer_mode': 'verified', 'outcome': outcome, 'elapsed_ms': elapsed,
            'detail_bridge': bridge, 'failures': failures,
            'webgl_context': _webgl_context(raw.get('webgl_context')),
            'fault_injection': bool(faults),
            'graph_fault_injected': 'mood-axis-graph' in faults,
            'requests': [{**{key: r.get(key) for key in ('route', 'method', 'status')},
                          'outcome': _request_outcome(r, scenario, bool(faults)),
                          'elapsed_ms': (r['headers_ms'] - r['request_ms']) if r.get('headers_ms') is not None else None}
                         for r in raw.get('requests', [])],
            'milestones_ms': {}, 'responsiveness': {'frame_gaps_ms': [], 'long_tasks_ms': [],
                'input_latency_ms': [], 'frame_count': 0, 'long_tasks_status': 'unavailable'}}
