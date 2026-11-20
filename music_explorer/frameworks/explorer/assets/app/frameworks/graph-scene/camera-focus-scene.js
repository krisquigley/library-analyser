// The camera focus's work on the vendored camera and Trackball controls (#146). The bundled camera setter's timed
// tweens have no public cancellation, so every pose is written at once and the arc's timeline is owned outside.

const TRACKBALL_SETTINGS = Object.freeze(['staticMoving', 'dynamicDampingFactor', 'rotateSpeed', 'zoomSpeed', 'panSpeed',
  'noZoom', 'noPan', 'noRotate', 'minDistance', 'maxDistance']);
// Zero speeds consume input endpoints; full dynamic damping clears residual rotation; no limits, so the drain
// can never be refused.
const DRAINING_SETTINGS = Object.freeze({staticMoving: false, dynamicDampingFactor: 1, rotateSpeed: 0, zoomSpeed: 0,
  panSpeed: 0, noZoom: false, noPan: false, noRotate: false, minDistance: 0, maxDistance: Infinity});
// A canonical pose keeps the draining update safe even when the listener's own radius overflows.
const DRAINING_POSE = Object.freeze({position: Object.freeze({x: 0, y: 0, z: 100}), target: Object.freeze({x: 0, y: 0, z: 0})});

// With the controls disabled, the bundled setter looks at the point but leaves the orbit target stale; the
// target is kept in step for the next update and for re-enabling.
export function setCameraFocusPose(graph, position, target) {
  const controls = graph.controls?.();
  if (controls?.target) Object.assign(controls.target, target);
  graph.cameraPosition(position, target, 0);
}

export function showCameraArcPose(graph, {position, target, up}) {
  const camera = graph.camera();
  if (up && camera.up?.set) camera.up.set(up.x, up.y, up.z);
  setCameraFocusPose(graph, position, target);
}

// Input the Trackball has taken in but not applied would otherwise turn the camera after the focus lands.
// It is drained once through the public API, and the listener's pose and settings are put back however that ends.
export function settleCameraFocusInput(graph) {
  const controls = graph.controls();
  const camera = graph.camera();
  if (typeof controls.update !== 'function') return;
  const position = {...graph.cameraPosition()};
  const target = {...controls.target};
  const up = camera.up ? {...camera.up} : null;
  const orientation = camera.quaternion?.clone ? camera.quaternion.clone() : null;
  const settings = Object.fromEntries(TRACKBALL_SETTINGS.map(name => [name, controls[name]]));
  try {
    Object.assign(controls, DRAINING_SETTINGS);
    if (camera.up?.set) camera.up.set(0, 1, 0);
    setCameraFocusPose(graph, DRAINING_POSE.position, DRAINING_POSE.target);
    controls.update();
  } finally {
    Object.assign(controls, settings);
    if (up && camera.up?.set) camera.up.set(up.x, up.y, up.z);
    setCameraFocusPose(graph, position, target);
    if (orientation) camera.quaternion.copy(orientation);
  }
}

// The listener starting to move the camera claims the view. It keeps only the controls it listens to.
export function createCameraControlsWatch({onControlsReplaced, onViewClaimed}) {
  let watched = null;
  const claimView = () => onViewClaimed();

  function observe(graph) {
    const controls = typeof graph?.controls === 'function' ? graph.controls() : null;
    if (controls === watched) return;
    onControlsReplaced();
    watched?.removeEventListener?.('start', claimView);
    watched = controls;
    controls?.addEventListener?.('start', claimView);
  }

  return Object.freeze({observe});
}
