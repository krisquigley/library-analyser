"""Explicit public synthetic Chromium diagnostic, not catalogue/server speed evidence."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import platform
import re
import tempfile
import time
from urllib.parse import urlsplit

def publish_browser_report(*args, **kwargs):
    """Public compatibility boundary for the separate supplied-observation policy."""
    from tools.explorer_browser_report import publish_browser_report as publish
    return publish(*args, **kwargs)

from tools.explorer_browser_routes import public_routes

SCENARIOS = ('pending-then-ready', 'graph-failure-retry', 'search-failure', 'latest-selection', 'during-consumption')
WRITER_SCENARIOS = ('pending-then-ready', 'graph-failure-retry', 'search-failure',
                    'latest-selection', 'rejected-post', 'detail-timeout')
PROBE = Path(__file__).with_name('explorer_browser_probe.js')


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('--real-browser', action='store_true')
    result.add_argument('--graph-profile', choices=('small', 'stress-41mib'), default='small')
    result.add_argument('--fixture-source', choices=('browser-only', 'writer-v10'), default='browser-only')
    result.add_argument('--track-count', type=int, default=12)
    result.add_argument('--seed', type=int, default=70)
    result.add_argument('--history-count', type=int, default=2)
    result.add_argument('--allow-large', action='store_true')
    result.add_argument('--scenario', choices=tuple(dict.fromkeys(SCENARIOS + WRITER_SCENARIOS)), default=SCENARIOS[0])
    result.add_argument('--observer-mode', choices=('verified', 'native-json'), default='verified')
    result.add_argument('--samples', type=int, default=1)
    result.add_argument('--sample-profile', choices=('process-cold', 'warm'), default='process-cold')
    result.add_argument('--wait-timeout-ms', type=int, default=10000)
    result.add_argument('--viewport', default='1280x720')
    result.add_argument('--output', type=Path, required=True)
    return result


def require_memory_bound():
    """A browser's large reserved address space is not a RAM consumption limit."""
    try:
        limit = int(Path('/sys/fs/cgroup/memory.max').read_text().strip())
        group = Path('/sys/fs/cgroup/memory.oom.group').read_text().strip()
        swap = Path('/sys/fs/cgroup/memory.swap.max').read_text().strip()
        if 0 < limit <= 4 * 2**30 and group == '1' and swap == '0':
            return
    except (OSError, ValueError):
        pass
    raise RuntimeError('require external cgroup memory.max <=4GiB and memory.oom.group=1')


def observe(page, url, release, scenario, observer_mode='verified', input_attempts=None):
    input_attempts = input_attempts if input_attempts is not None else []
    # Safety timeout, not a responsiveness target. Leave time for partial retention
    # inside the external 45s hard-wall supervisor.
    page.set_default_timeout(10000)
    page.add_init_script('window.__diagnosticObserverMode=' + json.dumps(observer_mode) + ';\n' + PROBE.read_text())
    page.goto(url, wait_until='domcontentloaded')
    page.wait_for_function("typeof buildMoodGraphModel==='function' && document.getElementById('track-search')")
    # Decorate existing entrypoints only after packaged startup has begun; the
    # held graph route makes model/render/focus instrumentation race-free.
    page.evaluate("""() => {
      const d=window.__diagnostic, m=d.milestones_ms, stamp=k=>m[k]=performance.now();
      const model=buildMoodGraphModel;buildMoodGraphModel=function(){
        const first=m.graph_model_start==null;if(first)stamp('graph_model_start');
        const value=model.apply(this,arguments);
        if(first){stamp('graph_model_end');m.graph_model=m.graph_model_end;}return value;
      };
      const scene=renderMap;renderMap=function(){
        const first=m.graph_scene_start==null;if(first)stamp('graph_scene_start');
        const value=scene.apply(this,arguments);
        if(first){stamp('graph_scene_end');requestAnimationFrame(()=>{if(m.graph_first_presentation==null)stamp('graph_first_presentation');});}
        return value;
      };
      const detail=renderDetail;renderDetail=function(){const value=detail.apply(this,arguments);stamp('detail_painted');return value;};
      const loading=renderDetailLoading;renderDetailLoading=function(){const value=loading.apply(this,arguments);if(m.selection_intent!=null)stamp('selection_feedback');return value;};
      const select=setCurrent;setCurrent=function(){stamp('selection_intent');return select.apply(this,arguments);};
      const focus=animateCameraFocus;animateCameraFocus=function(){stamp('focus_start');d.consumed_count++;return focus.apply(this,arguments);};
      stamp('search_usable');
    }""")
    page.wait_for_function("state.selection_epoch!=null")
    initial = page.evaluate("window.__diagnostic.requests.filter(r=>r.route==='/api/tracks/summary').length")
    graph_error = False
    if scenario == 'graph-failure-retry':
        page.wait_for_function("graphLoadState.status==='error'")
        graph_error = page.locator('#graph-load-status [role=alert]').is_visible()
        page.get_by_role('button', name='Retry graph').click()
    page.evaluate("window.__diagnostic.milestones_ms.search_input=performance.now()")
    page.locator('#track-search').fill('Public')
    search_error = False
    if scenario == 'search-failure':
        page.wait_for_function("trackSummaryStatus==='error'")
        search_error = page.get_by_role('button', name='Retry search').is_visible()
        page.get_by_role('button', name='Retry search').click()
    page.wait_for_function("trackSummaryStatus==='ready' && trackSummaryPage.tracks.length>0")
    page.evaluate("window.__diagnostic.milestones_ms.search_rows=performance.now()")
    page.locator('#tracks tbody tr').first.click()
    page.wait_for_function("document.getElementById('detail').getAttribute('aria-busy')==='false' && state.current_track_id==='public-00000' && pendingSelectionOperation===null")
    if scenario == 'latest-selection':
        page.locator('#tracks tbody tr').nth(1).click()
        page.wait_for_function("document.getElementById('detail').getAttribute('aria-busy')==='false' && state.current_track_id==='public-00001' && pendingSelectionOperation===null")
    # Hold until an actual presentation frame, not just a DOM mutation.
    page.evaluate("() => new Promise(resolve=>requestAnimationFrame(()=>{window.__diagnostic.milestones_ms.detail_painted=performance.now();resolve();}))")
    if scenario == 'during-consumption':
        # Arm before any body/CPU work; no synchronous page evaluate is used
        # between active-consumption observation and a trusted host dispatch.
        page.evaluate("window.__diagnostic.contention_action='armed'")
    release.set()
    if scenario == 'during-consumption':
        phase = 'native-json' if observer_mode == 'native-json' else 'body'
        prefix = 'graph_native_json' if observer_mode == 'native-json' else 'graph_body'
        active = f"window.__diagnostic.milestones_ms.{prefix}_start!=null && window.__diagnostic.milestones_ms.{prefix}_end==null"
        page.wait_for_function(active)
        attempt = new_input_attempt('input', phase)
        input_attempts.append(attempt)
        page.locator('#track-search').fill('Public synthetic')
        # A paced actual body is still incomplete here; reobserve rather than
        # inventing that the first body's phase also applies to selection.
        page.wait_for_function(active)
        attempt = new_input_attempt('selection', phase)
        input_attempts.append(attempt)
        if hasattr(release, 'body_release'):
            release.body_release.set()
        page.locator('#tracks tbody tr').nth(1).click()
        page.wait_for_function("document.getElementById('detail').getAttribute('aria-busy')==='false' && state.current_track_id==='public-00001' && pendingSelectionOperation===null")
    page.wait_for_function("graphLoadState.status==='ready'  && forceGraph && selectedNodeHalo && cameraFocusFrame===null && window.__diagnostic.milestones_ms.focus_start!=null")
    page.evaluate("window.__diagnostic.milestones_ms.focus_end=performance.now()")
    # Read real WebGL pixels in-memory in a render callback; no screenshots,
    # HAR, response bodies, or private IDs are publication artifacts.
    result = page.evaluate("""() => new Promise(resolve=>requestAnimationFrame(()=>{
      const d=window.__diagnostic, renderer=forceGraph.renderer(), canvas=renderer.domElement;
      renderer.render(forceGraph.scene(),forceGraph.camera());
      const gl=renderer.getContext(), pixels=new Uint8Array(canvas.width*canvas.height*4);
      gl.readPixels(0,0,canvas.width,canvas.height,gl.RGBA,gl.UNSIGNED_BYTE,pixels);
      let changed=false;for(let i=4;i<pixels.length;i+=4){if(pixels[i]!==pixels[0]||pixels[i+1]!==pixels[1]||pixels[i+2]!==pixels[2]){changed=true;break;}}
      const node=renderedGraphData.nodes.find(n=>n.id===state.current_track_id), point=forceGraph.graph2ScreenCoords(node.x,node.y,node.z), box=canvas.getBoundingClientRect();
      const mesh=findSceneObject(forceGraph.scene(),obj=>graphObjectTrackId(obj)===state.current_track_id && obj.geometry && obj.name!=='selected-node-halo');
      const camera=forceGraph.camera(), halo=selectedNodeHalo.mesh;
      d.milestones_ms.graph_post_focus_readback=performance.now();
      d.milestones_ms.graph_usable_render=d.milestones_ms.graph_post_focus_readback;
      const debug=gl.getExtension('WEBGL_debug_renderer_info');
      const implementation=debug?String(gl.getParameter(debug.UNMASKED_RENDERER_WEBGL)).toLowerCase():'';
      const context={api_version:String(gl.getParameter(gl.VERSION)),
        vendor:gl.getParameter(gl.VENDOR)==='WebKit'?'WebKit':'unclassified',
        renderer:gl.getParameter(gl.RENDERER)==='WebKit WebGL'?'WebKit WebGL':'unclassified',
        implementation:implementation.includes('swiftshader')?'software-swiftshader':
          (implementation.includes('llvmpipe')||implementation.includes('softpipe'))?'software-other':'unclassified'};
      resolve({...d, webgl:!!gl, webgl_context:context, render:{canvas_visible:box.width>0&&box.height>0,nonempty_pixels:changed,positioned_nodes_visible:!!mesh&&mesh.visible!==false},
        focus:{selected_node_in_view:point.x>=0&&point.y>=0&&point.x<=box.width&&point.y<=box.height,
          halo_visible:!!halo.parent&&halo.visible!==false,finite_camera:['x','y','z'].every(k=>Number.isFinite(camera.position[k])),consumed_count:d.consumed_count},
        selection:{accepted:state.current_track_id!=null&&pendingSelectionOperation===null,
          latest_accepted:state.current_track_id==='public-00001'&&selectedNodeHalo.trackId===state.current_track_id}});
    }))""")
    result.update(profile='process-cold', clock='browser-performance',
                  ui_source='packaged-explorer-assets', browser_evidence='real-playwright-chromium',
                  outcome='ok', elapsed_ms=result['milestones_ms']['graph_usable_render'],
                  initial_sidebar_requests=initial, graph_error_visible=graph_error,
                  graph_retry_count=int(graph_error), search_error_visible=search_error,
                  search_retry_count=int(search_error))
    result.pop('consumed_count', None)
    result['failures'] = request_failures(result['requests'])
    if not all(result['render'].values()):
        record_invalid_response(result, 'graph')
    if (not all(v for k, v in result['focus'].items() if k != 'consumed_count')
            or not result['selection']['accepted']
            or (result['focus']['consumed_count'] < 1 if scenario == 'during-consumption' and
                any(receipt.get('is_trusted') is True and receipt.get('action') in (None, 'selection')
                    for receipt in result.get('input_observations', []))
                else result['focus']['consumed_count'] != 1)
            or (scenario in ('latest-selection', 'during-consumption')
                and not result['selection']['latest_accepted'])):
        record_invalid_response(result, 'selection')
    return result


def request_failures(requests):
    """Count observed failed requests, not duplicate UI summaries of a retry."""
    flows = {'/api/mood-axis-graph': 'graph', '/api/tracks/summary': 'search',
             '/api/current': 'selection', '/api/tracks/<id>': 'selection'}
    failures = []
    for request in requests:
        flow = flows.get(request.get('route'))
        outcome = request.get('outcome')
        # The probe initializes pending requests as connection_error with no
        # elapsed time. Those are not observed failures yet.
        if flow and (outcome == 'http_error' or
                     (outcome in ('connection_error', 'timeout')
                      and request.get('elapsed_ms') is not None)):
            failures.append({'flow': flow, 'outcome': outcome})
    return failures


def record_invalid_response(sample, flow):
    sample['outcome'] = 'invalid_response'
    failure = {'flow': flow, 'outcome': 'invalid_response'}
    if failure not in sample['failures']:
        sample['failures'].append(failure)


MILESTONES = ('navigation', 'graph_request', 'graph_headers', 'graph_body',
              'graph_json', 'graph_model', 'graph_usable_render', 'search_usable',
              'search_input', 'search_rows', 'selection_intent', 'selection_feedback',
              'detail_painted', 'focus_start', 'focus_end',
              'graph_body_start', 'graph_body_end', 'graph_json_start', 'graph_json_end',
              'graph_verification_start', 'graph_verification_end',
              'graph_native_json_start', 'graph_native_json_end',
              'graph_model_start', 'graph_model_end', 'graph_scene_start', 'graph_scene_end',
              'graph_first_presentation', 'graph_post_focus_readback')


def new_input_attempt(action, phase):
    """Host intent cannot be subtracted from a browser performance clock."""
    return {'action': action, 'attempt_clock': 'host-monotonic',
            'attempt_ms': time.monotonic() * 1000, 'phase_at_attempt': phase,
            'receipt_clock': 'browser-performance', 'received_ms': None,
            'frame_ms': None, 'is_trusted': None, 'phase_at_receipt': None,
            'outcome': 'unavailable'}


def merge_input_observations(attempts, receipts, outcome):
    """Match known action labels, retaining host intent even if page recovery fails."""
    result = [dict(attempt) for attempt in attempts]
    used = set()
    for index, attempt in enumerate(result):
        matching = next((i for i, receipt in enumerate(receipts)
                         if i not in used and receipt.get('action') == attempt['action']), None)
        # Compatibility with supplied legacy receipt observations lacking action.
        # They refer to the final host action; never invent an earlier receipt.
        if matching is None and index == len(result) - 1:
            matching = next((i for i, receipt in enumerate(receipts)
                             if i not in used and 'action' not in receipt), None)
        if matching is not None:
            used.add(matching)
            receipt = receipts[matching]
            for key in ('receipt_clock', 'received_ms', 'frame_ms', 'is_trusted', 'phase_at_receipt'):
                if key in receipt:
                    attempt[key] = receipt[key]
        received, frame = attempt['received_ms'], attempt['frame_ms']
        valid_pair = (all(isinstance(value, (int, float)) and not isinstance(value, bool)
                          and math.isfinite(value) and value >= 0 for value in (received, frame))
                      and frame >= received)
        if not valid_pair:
            attempt['frame_ms'] = None
            if not (isinstance(received, (int, float)) and not isinstance(received, bool)
                    and math.isfinite(received) and received >= 0):
                attempt['received_ms'] = None
                attempt['is_trusted'] = None
        attempt['outcome'] = (outcome if outcome != 'ok' else
                              'unavailable' if matching is None else
                              'ok' if attempt['is_trusted'] is True and valid_pair else 'invalid_response')
    return result


def contention_status(records):
    if len(records) == 2 and all(record['outcome'] == 'ok' for record in records):
        return 'observed-trusted-input'
    if any(record['outcome'] == 'invalid_response' for record in records):
        return 'invalid_response'
    return 'unavailable'


def observe_attempt(page, url, release, scenario, observer_mode='verified'):
    """Retain one failed lifecycle without publishing exception text or invented times."""
    if hasattr(release, 'writer_fixture'):
        from tools.explorer_db_detail_browser import observe_writer_attempt
        return observe_writer_attempt(page, url, scenario, observer_mode, release.writer_fixture,
                                      wait_timeout_ms=getattr(release, 'writer_wait_timeout_ms', 10000))
    assets = []
    input_attempts = []

    def finished(request):
        if urlsplit(request.url).path.startswith('/api/'):
            return
        response = request.response()
        assets.append({'route': 'asset', 'method': request.method,
                       'status': response.status if response else None,
                       'outcome': 'ok' if response and response.ok else 'http_error',
                       'elapsed_ms': (request.timing['responseEnd']
                                      if request.timing['responseEnd'] >= 0 else None)})

    def failed(request):
        if not urlsplit(request.url).path.startswith('/api/'):
            assets.append({'route': 'asset', 'method': request.method,
                           'outcome': 'connection_error', 'elapsed_ms': None})

    page.on('requestfinished', finished)
    page.on('requestfailed', failed)
    try:
        result = observe(page, url, release, scenario, observer_mode, input_attempts)
        result['observer_mode'] = observer_mode
        if input_attempts:
            result['input_observations'] = merge_input_observations(input_attempts, result.get('input_observations', []), 'ok')
        if scenario == 'during-consumption':
            result['contention_status'] = contention_status(result.get('input_observations', []))
        result['requests'].extend(assets)
        return result
    except Exception as error:
        outcome = 'timeout' if type(error).__name__ == 'TimeoutError' else 'invalid_response'
        try:
            partial = page.evaluate('window.__diagnostic') or {}
        except Exception:
            partial = {}
        milestones = {key: partial.get('milestones_ms', {}).get(key) for key in MILESTONES}
        result = {'profile': 'process-cold', 'clock': 'browser-performance',
                'ui_source': 'packaged-explorer-assets', 'browser_evidence': 'real-playwright-chromium',
                'outcome': outcome, 'elapsed_ms': None, 'milestones_ms': milestones,
                'requests': partial.get('requests', []) + assets,
                'responsiveness': partial.get('responsiveness', {
                    'frame_gaps_ms': [], 'long_tasks_ms': [], 'input_latency_ms': [],
                    'frame_count': 0, 'long_tasks_status': 'unavailable'}),
                'failures': request_failures(partial.get('requests', [])) +
                            [{'flow': 'lifecycle', 'outcome': outcome}]}
        result['observer_mode'] = observer_mode
        if 'graph_response' in partial:
            result['graph_response'] = partial['graph_response']
        if input_attempts:
            result['input_observations'] = merge_input_observations(input_attempts, partial.get('input_observations', []), outcome)
        if scenario == 'during-consumption':
            result['contention_status'] = 'unavailable'
        return result


def validate_graph_response(sample, manifest):
    """Successful browser consumption must match the independently generated identity."""
    if sample['outcome'] != 'ok' and 'graph_response' not in sample:
        return
    expected = {'content_encoding': manifest['content_encoding'],
                'content_length': manifest['encoded']['body_bytes'],
                'consumed_bytes': manifest['decoded']['body_bytes'],
                'consumed_sha256': manifest['decoded']['sha256'],
                'json_counts': manifest['counts']}
    observed = sample.get('graph_response', {})
    native = sample.get('observer_mode') == 'native-json'
    if native:
        expected.update(consumed_bytes=None, consumed_sha256=None,
                        consumed_identity_status='unavailable-native-json')
    elif 'consumed_identity_status' in observed:
        expected['consumed_identity_status'] = 'verified'
    if observed != expected:
        record_invalid_response(sample, 'graph')


def failed_setup_attempt(error):
    """Publish only a classified outcome for setup, before any page observation."""
    outcome = 'timeout' if type(error).__name__ == 'TimeoutError' else 'invalid_response'
    return {'profile': 'process-cold', 'clock': 'browser-performance',
            'ui_source': 'packaged-explorer-assets', 'browser_evidence': 'real-playwright-chromium',
            'outcome': outcome, 'elapsed_ms': None, 'milestones_ms': dict.fromkeys(MILESTONES),
            'requests': [], 'responsiveness': {
                'frame_gaps_ms': [], 'long_tasks_ms': [], 'input_latency_ms': [],
                'frame_count': 0, 'long_tasks_status': 'unavailable'},
            'failures': [{'flow': 'lifecycle', 'outcome': outcome}]}


def collect(args, viewport):
    from tools.explorer_browser_graph_fixture import public_browser_graph_fixture
    from playwright.sync_api import sync_playwright
    require_memory_bound()
    if getattr(args, 'fixture_source', 'browser-only') == 'writer-v10':
        return collect_writer(args, viewport, sync_playwright)
    if args.scenario not in SCENARIOS:
        raise ValueError('Writer-only fault scenario requires writer-v10 source')
    fixture = public_browser_graph_fixture(profile=args.graph_profile, allow_large=args.allow_large)
    samples = []
    version = None
    # Writable bounded-owned XDG avoids root HOME crashpad trouble without
    # changing browser flags. The entire scratch tree is removed after close.
    import os
    with tempfile.TemporaryDirectory(prefix='public-browser-') as scratch:
        config, cache = Path(scratch) / 'config', Path(scratch) / 'cache'
        config.mkdir(); cache.mkdir()
        env = dict(os.environ, XDG_CONFIG_HOME=str(config), XDG_CACHE_HOME=str(cache))
        with sync_playwright() as driver:
            for _ in range(args.samples):
                with public_routes(fixture, args.scenario) as (url, release):
                    browser = None
                    try:
                        try:
                            browser = driver.chromium.launch(channel='chromium', timeout=15000, env=env)
                            version = browser.version
                            page = browser.new_page(viewport=viewport)
                            if not page.evaluate("!!document.createElement('canvas').getContext('webgl2')"):
                                raise RuntimeError('Chromium WebGL preflight failed')
                        except Exception as error:
                            samples.append(failed_setup_attempt(error))
                            continue
                        sample = observe_attempt(page, url, release, args.scenario, getattr(args, 'observer_mode', 'verified'))
                        validate_graph_response(sample, fixture['manifest'])
                        samples.append(sample)
                    finally:
                        if browser is not None:
                            browser.close()
    counts = Counter(f"{f['flow']}:{f['outcome']}" for s in samples for f in s['failures'])
    return {'scope': 'public-synthetic-browser-only', 'browser_evidence': 'real-playwright-chromium',
            'latency_budget_result': 'not_asserted', 'scenario': args.scenario,
            'observer_mode': getattr(args, 'observer_mode', 'verified'),
            'graph_fixture': fixture['manifest'], 'samples': samples,
            'attempted': len(samples), 'succeeded': sum(s['outcome'] == 'ok' for s in samples),
            'failure_counts': dict(counts), 'environment': {
                'browser': {'engine': 'chromium', 'driver': 'playwright', 'version': version},
                'viewport': viewport, 'python_version': platform.python_version(),
                'platform': platform.system(), 'architecture': platform.machine(),
                'logical_cpu_count': os.cpu_count(),
                'rss': {'status': 'unavailable', 'peak_bytes': None}},
            'limitations': ['Public synthetic routes, not SQLite speed or catalogue realism.',
                            'Process-cold browser, not disk-cold; diagnostic instrumentation adds overhead.',
                            'Verified mode UTF-8/hash adds overhead; native-json uses native response.json and leaves separate parse/consumed identity unavailable.',
                            'First presentation is a next-frame proxy, not physical display or GPU completion; readback is separate.',
                            'No absolute latency budget; RSS unavailable.']}


def collect_writer(args, viewport, sync_playwright):
    """Outward composition of an owned writer fixture and unchanged packaged server.

    No private paths are accepted. Fingerprints are compared only while the
    disposable fixture remains owned and quiescent, after server shutdown.
    Cleanup flags describe context completion, not external process supervision.
    """
    import os
    from types import SimpleNamespace
    from music_explorer.frameworks.explorer.server import create_server
    from tools.explorer_synthetic_fixture import public_synthetic_fixture, _validate_options
    from tools.explorer_fixture_inspection import fingerprint_sqlite_files
    from tools.explorer_http_diagnostic import _running_server
    from tools.explorer_writer_server_observation import BoundedWriterServerObservation
    from tools.explorer_http_report import publish_http_report

    _validate_options(args.track_count, args.seed, args.history_count, args.allow_large)
    if args.scenario not in WRITER_SCENARIOS:
        raise ValueError('Unsupported writer scenario')
    if args.graph_profile != 'small':
        raise ValueError('Writer source cannot use browser-only inflated graph profile')
    if getattr(args, 'observer_mode', 'verified') != 'verified':
        raise ValueError('Writer bridge requires verified observation')
    if type(args.samples) is not int or not 1 <= args.samples <= 100:
        raise ValueError('Require 1..100 samples')
    sample_profile = getattr(args, 'sample_profile', 'process-cold')
    if sample_profile not in ('process-cold', 'warm'):
        raise ValueError('Require process-cold or warm sample profile')
    wait_timeout_ms = getattr(args, 'wait_timeout_ms', 10000)
    if type(wait_timeout_ms) is not int or not 10000 <= wait_timeout_ms <= 120000:
        raise ValueError('Require writer wait timeout 10000..120000 ms')
    warmup_completed = 0
    samples, browser_cleanup = [], []
    version = None
    server_closed = False
    server_observation = BoundedWriterServerObservation()
    def observed_factory(*factory_args, **factory_kwargs):
        return server_observation.instrument_server(create_server(*factory_args, **factory_kwargs))
    with public_synthetic_fixture(track_count=args.track_count, seed=args.seed,
                                  history_count=args.history_count,
                                  allow_large=args.allow_large) as fixture:
        manifest = fixture['manifest']
        before = fingerprint_sqlite_files(fixture['db_path'])
        with tempfile.TemporaryDirectory(prefix='public-browser-') as scratch:
            config, cache = Path(scratch) / 'config', Path(scratch) / 'cache'
            config.mkdir(); cache.mkdir()
            env = dict(os.environ, XDG_CONFIG_HOME=str(config), XDG_CACHE_HOME=str(cache))
            with server_observation.installed(), sync_playwright() as driver:
                try:
                    for _ in range(args.samples):
                        # Browser pages are fresh, but accepted selections live in the
                        # server session. Own a fresh server for each complete sample,
                        # including that sample's optional same-page warmup.
                        with _running_server(observed_factory, fixture['db_path']) as url:
                            browser = None
                            closed = False
                            sample = None
                            try:
                                browser = driver.chromium.launch(channel='chromium', timeout=15000, env=env)
                                version = browser.version
                                page = browser.new_page(viewport=viewport)
                                if not page.evaluate("!!document.createElement('canvas').getContext('webgl2')"):
                                    raise RuntimeError('Chromium WebGL preflight failed')
                                if sample_profile == 'warm':
                                    # Prime this same browser/page with actual packaged startup;
                                    # no observer is injected and no timing sample is recorded.
                                    page.set_default_timeout(wait_timeout_ms)
                                    page.goto(url, wait_until='domcontentloaded')
                                    page.wait_for_function("typeof graphLoadState!=='undefined' && graphLoadState.status==='ready'")
                                    warmup_completed += 1
                                release = SimpleNamespace(writer_fixture=fixture,
                                                          writer_wait_timeout_ms=wait_timeout_ms)
                                sample = observe_attempt(page, url, release, args.scenario, 'verified')
                            except Exception as error:
                                sample = failed_setup_attempt(error)
                            finally:
                                if browser is not None:
                                    try:
                                        browser.close()
                                        closed = True
                                    except Exception:
                                        if sample is None:
                                            sample = failed_setup_attempt(RuntimeError())
                                        record_invalid_response(sample, 'lifecycle')
                                else:
                                    # No browser was returned, so there is no owned handle to close.
                                    closed = True
                            sample['profile'] = sample_profile
                            samples.append(sample)
                            browser_cleanup.append(closed)
                    server_closed = True
                except Exception as error:
                    # Retain completed attempts when server setup/shutdown fails.
                    if not samples:
                        sample = failed_setup_attempt(error)
                        sample['profile'] = sample_profile
                        samples.append(sample)
                        browser_cleanup.append(True)
                    else:
                        for sample in samples:
                            record_invalid_response(sample, 'lifecycle')
        scratch_removed = not Path(scratch).exists()
        unchanged = before == fingerprint_sqlite_files(fixture['db_path'])
        for sample, closed in zip(samples, browser_cleanup):
            bridge = sample.setdefault('detail_bridge', {})
            bridge.update(fixture=manifest, server='packaged-explorer-loopback',
                          database_unchanged=unchanged,
                          cleanup={'browser_closed': closed, 'server_closed': server_closed,
                                   'scratch_removed': scratch_removed})
            bridge.setdefault('server_phases', {'status': 'unavailable', 'clock': None, 'spans': None})
            if not unchanged:
                record_invalid_response(sample, 'lifecycle')
    # Raw observations are always passed through the public allowlist boundary.
    report = publish_browser_report(attempts=samples)
    counts = Counter(f"{f['flow']}:{f['outcome']}"
                     for sample in report['samples'] for f in sample.get('failures', []))
    server_requests = [dict(method=request['method'],
                            url='http://127.0.0.1' + request['route'],
                            observer_mode='observer_on', server_spans=request['spans'])
                       for request in server_observation.requests]
    report['server_observation'] = publish_http_report(
        attempts=[], requests=server_requests)['server_observation']
    sampling = server_observation.sampling_report()
    report['server_observation']['sampling'] = sampling
    if sampling['status'] == 'sampled':
        # Omitted children cannot be subtracted as if all intervals were retained.
        for span in report['server_observation']['spans']:
            span['exclusive_ms'] = None
        for phase, phase_counts in sampling['phases'].items():
            if phase_counts['omitted']:
                report['server_observation']['phases'][phase]['status'] = 'sampled'
        report['server_observation']['status'] = 'sampled'
    else:
        spans = report['server_observation']['spans']
        report['server_observation']['status'] = (
            'unavailable' if not spans else
            'partial' if any(span['status'] != 'ok' for span in spans) else 'observed')
    report['server_observation']['browser_request_correlation'] = 'unavailable'
    report['server_observation']['includes_warmup_requests'] = sample_profile == 'warm'
    report['warmup'] = {'profile': sample_profile, 'completed': warmup_completed,
                        'scope': 'same-browser-page-packaged-startup' if sample_profile == 'warm' else 'none',
                        'disk_cache_state': 'not_established'}
    report.update(scope='public-synthetic-sqlite-browser', fixture=manifest,
                  browser_evidence='real-playwright-chromium', latency_budget_result='not_asserted',
                  scenario=args.scenario, observer_mode='verified', attempted=len(samples),
                  safety_wait_timeout_ms=wait_timeout_ms,
                  succeeded=sum(sample['outcome'] == 'ok' for sample in report['samples']),
                  failure_counts=dict(counts), environment={
                      'browser': {'engine': 'chromium', 'driver': 'playwright', 'version': version},
                      'viewport': viewport, 'python_version': platform.python_version(),
                      'platform': platform.system(), 'architecture': platform.machine(),
                      'logical_cpu_count': os.cpu_count(),
                      'rss': {'status': 'unavailable', 'peak_bytes': None}},
                  limitations=['Public writer-v10 fixture; no private-library or latency-budget claim.',
                               'Merged server observer phases are request-local; browser correlation is unavailable and clocks are not combined.',
                               'Verified text/parse/hash observation adds overhead.',
                               'DOM-ready and next-frame are not physical paint or GPU completion.',
                               'Cleanup flags do not replace external descendant supervision.'])
    return report


def main():
    cli = parser()
    args = cli.parse_args()
    if not args.real_browser:
        cli.error('execution requires --real-browser')
    if not 1 <= args.samples <= 100:
        cli.error('--samples must be 1..100')
    match = re.fullmatch(r'([1-9][0-9]*)x([1-9][0-9]*)', args.viewport)
    if not match or any(int(n) > 4096 for n in match.groups()):
        cli.error('--viewport must be WIDTHxHEIGHT within 1..4096')
    if args.graph_profile != 'small' and not args.allow_large:
        cli.error('stress-41mib requires --allow-large')
    viewport = dict(zip(('width', 'height'), map(int, match.groups())))
    try:
        report = collect(args, viewport)
        args.output.write_text(json.dumps(report, allow_nan=False, indent=2) + '\n')
    except Exception:
        # No traceback, paths, browser launch command, environment or URL echo.
        cli.exit(1, 'Public browser diagnostic failed; verify bounded Chromium/WebGL environment and lifecycle.\n')


if __name__ == '__main__':
    main()
