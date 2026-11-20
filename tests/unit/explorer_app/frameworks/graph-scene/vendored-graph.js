// The vendored 3d-force-graph bundle, loaded in Node so the graph scene can be tested against its real THREE,
// Trackball and camera setter (#146). The bundle keeps them private; this reaches them through the same seams as
// the page-level camera harness, and fails loudly if the bundle changes. Not a test file: the runner skips it.
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {createContext, runInContext} from 'node:vm';

const BUNDLE = fileURLToPath(new URL(
  '../../../../../music_explorer/frameworks/explorer/assets/vendor/3d-force-graph/3d-force-graph.min.js', import.meta.url));
const CLOSURE_END = 'return Ok});';

export function loadVendoredGraph() {
  let source = readFileSync(BUNDLE, 'utf8').trimEnd();
  const start = source.indexOf('cameraPosition:function(e,t,n,i)');
  const end = source.indexOf(',zoomToFit:', start);
  if (start < 0 || end < 0 || !source.endsWith(CLOSURE_END)) throw new Error('The vendored bundle changed: review this loader');
  const cameraPosition = source.slice(start + 'cameraPosition:'.length, end);
  source = source.slice(0, -CLOSURE_END.length)
    + `globalThis.vendoredGraph={Group:oO,THREE:Ak,Trackball:cU,cameraPosition:${cameraPosition}};` + CLOSURE_END;
  let now = 0;
  const context = createContext({console, setTimeout, clearTimeout, setInterval, clearInterval, window: {}, performance: {now: () => now}});
  runInContext(source, context, {filename: BUNDLE});
  return {...context.vendoredGraph, setTime: time => { now = time; }};
}

// A graph whose camera, Trackball controls and camera setter are the vendor's own.
export function vendoredGraphScene(vendor) {
  const camera = new vendor.THREE.PerspectiveCamera();
  camera.position.set(500, 400, 300);
  const controls = new vendor.Trackball(camera);
  Object.assign(controls.screen, {left: 0, top: 0, width: 800, height: 600});
  const state = {initialised: true, camera, controls, tweenGroup: new vendor.Group()};
  const graph = {
    camera: () => camera,
    controls: () => controls,
    cameraPosition(position, target, duration) {
      if (!position) return {...camera.position};
      vendor.cameraPosition(state, position, target, duration);
      return graph;
    },
  };
  const advance = time => { vendor.setTime(time); state.tweenGroup.update(time); };
  return {camera, controls, state, graph, advance};
}

// Listener input the Trackball has taken in but not yet applied, as a quick wheel, pan or orbit leaves it.
export const UNFLUSHED_INPUT = Object.freeze({
  wheel(controls) {
    controls._onMouseWheel({deltaMode: 0, deltaY: 120, preventDefault() {}});
    controls.update();
  },
  pan(controls) { drag(controls, 2); },
  orbit(controls) { drag(controls, 0); },
});

function drag(controls, button) {
  controls._onMouseDown({button, pageX: 400, pageY: 300});
  controls._onMouseMove({pageX: 500, pageY: 350});
  controls.update();
  controls._onMouseUp();
}
