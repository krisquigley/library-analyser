"""Explicit public synthetic Chromium diagnostic, not catalogue/server speed evidence."""
import argparse
from collections import Counter
import json
from pathlib import Path
import platform
import re
import tempfile
from urllib.parse import urlsplit

def publish_browser_report(*args, **kwargs):
    """Public compatibility boundary for the separate supplied-observation policy."""
    from tools.explorer_browser_report import publish_browser_report as publish
    return publish(*args, **kwargs)

from tools.explorer_browser_routes import public_routes

SCENARIOS = ('pending-then-ready', 'graph-failure-retry', 'search-failure', 'latest-selection')
PROBE = Path(__file__).with_name('explorer_browser_probe.js')


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('--real-browser', action='store_true')
    result.add_argument('--graph-profile', choices=('small', 'stress-41mib'), default='small')
    result.add_argument('--allow-large', action='store_true')
    result.add_argument('--scenario', choices=SCENARIOS, default=SCENARIOS[0])
    result.add_argument('--samples', type=int, default=1)
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


def observe(page, url, release, scenario):
    page.set_default_timeout(55000)
    page.add_init_script(PROBE.read_text())
    page.goto(url, wait_until='domcontentloaded')
    page.wait_for_function("typeof buildMoodGraphModel==='function' && document.getElementById('track-search')")
    # Decorate existing entrypoints only after packaged startup has begun; the
    # held graph route makes model/render/focus instrumentation race-free.
    page.evaluate("""() => {
      const d=window.__diagnostic, m=d.milestones_ms, stamp=k=>m[k]=performance.now();
      const model=buildMoodGraphModel;buildMoodGraphModel=function(){const value=model.apply(this,arguments);stamp('graph_model');return value;};
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
    release.set()
    page.wait_for_function("graphLoadState.status==='ready' && forceGraph && selectedNodeHalo && cameraFocusFrame===null && window.__diagnostic.milestones_ms.focus_start!=null")
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
      d.milestones_ms.graph_usable_render=performance.now();
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
            or result['focus']['consumed_count'] != 1
            or (scenario == 'latest-selection'
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
              'detail_painted', 'focus_start', 'focus_end')


def observe_attempt(page, url, release, scenario):
    """Retain one failed lifecycle without publishing exception text or invented times."""
    assets = []

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
        result = observe(page, url, release, scenario)
        result['requests'].extend(assets)
        return result
    except Exception as error:
        outcome = 'timeout' if type(error).__name__ == 'TimeoutError' else 'invalid_response'
        try:
            partial = page.evaluate('window.__diagnostic') or {}
        except Exception:
            partial = {}
        milestones = {key: partial.get('milestones_ms', {}).get(key) for key in MILESTONES}
        return {'profile': 'process-cold', 'clock': 'browser-performance',
                'ui_source': 'packaged-explorer-assets', 'browser_evidence': 'real-playwright-chromium',
                'outcome': outcome, 'elapsed_ms': None, 'milestones_ms': milestones,
                'requests': partial.get('requests', []) + assets,
                'responsiveness': partial.get('responsiveness', {
                    'frame_gaps_ms': [], 'long_tasks_ms': [], 'input_latency_ms': [],
                    'frame_count': 0, 'long_tasks_status': 'unavailable'}),
                'failures': request_failures(partial.get('requests', [])) +
                            [{'flow': 'lifecycle', 'outcome': outcome}]}


def validate_graph_response(sample, manifest):
    """Successful browser consumption must match the independently generated identity."""
    if sample['outcome'] != 'ok' and 'graph_response' not in sample:
        return
    expected = {'content_encoding': manifest['content_encoding'],
                'content_length': manifest['encoded']['body_bytes'],
                'consumed_bytes': manifest['decoded']['body_bytes'],
                'consumed_sha256': manifest['decoded']['sha256'],
                'json_counts': manifest['counts']}
    if sample.get('graph_response') != expected:
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
                        sample = observe_attempt(page, url, release, args.scenario)
                        validate_graph_response(sample, fixture['manifest'])
                        samples.append(sample)
                    finally:
                        if browser is not None:
                            browser.close()
    counts = Counter(f"{f['flow']}:{f['outcome']}" for s in samples for f in s['failures'])
    return {'scope': 'public-synthetic-browser-only', 'browser_evidence': 'real-playwright-chromium',
            'latency_budget_result': 'not_asserted', 'scenario': args.scenario,
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
                            'Consumed-body UTF-8 encoding and SHA256 hashing add bounded observer overhead.',
                            'Usable render is a verified post-focus GPU frame, not earliest presentation.',
                            'No absolute latency budget; RSS unavailable.']}


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
