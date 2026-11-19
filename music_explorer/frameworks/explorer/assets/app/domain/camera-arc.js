// The camera's focus on a track (#146): where to look from, and the arc that gets there.
// Camera focus is best-effort; a pose that cannot be represented reliably is skipped (null), never forced.

const ARC_AXES = Object.freeze(['x', 'y', 'z']);
export const CAMERA_FOCUS_MS = 700;
const FOCUS_RADIUS = 100;
const SMALLEST_NORMAL_SQUARE = 2 ** -1022;
// Three's Trackball squares offsets during lookAt; a larger radius cannot be represented once squared.
const SAFE_RADIUS = Math.sqrt(Number.MAX_VALUE) / 4;
const PARALLEL = 1e-8;

// Normalise by the largest component before measuring: finite wheel poses can have an
// overflowing radius, while subnormal gaps have overflowing reciprocals.
export function cameraUnitDirection(vector) {
  if (!ARC_AXES.every(axis => Number.isFinite(vector[axis]))) return null;
  const largest = Math.max(...ARC_AXES.map(axis => Math.abs(vector[axis])));
  if (largest === 0) return null;
  const scaled = mapAxes(axis => vector[axis] / largest);
  const length = Math.hypot(scaled.x, scaled.y, scaled.z);
  return mapAxes(axis => scaled[axis] / length);
}

export function cameraViewDirection(position, target) {
  if (!ARC_AXES.every(axis => Number.isFinite(position[axis]) && Number.isFinite(target[axis]))) return null;
  const offset = subtract(position, target);
  if (ARC_AXES.every(axis => Number.isFinite(offset[axis]))) return cameraUnitDirection(offset);
  // Opposite finite coordinates can overflow the subtraction too.
  const largest = Math.max(...ARC_AXES.flatMap(axis => [Math.abs(position[axis]), Math.abs(target[axis])]));
  return cameraUnitDirection(mapAxes(axis => position[axis] / largest - target[axis] / largest));
}

export function focusProgress(started, now) {
  return Math.min(1, Math.max(0, (now - started) / CAMERA_FOCUS_MS));
}

// The camera-relative offset turns on an arc, never through lookAt, and up is carried
// along that arc so passing a world-up pole cannot flip the roll.
export function cameraFocusArc({fromPosition, fromTarget, fromUp, position, target}) {
  const endOffset = subtract(position, target);
  const endDistance = magnitude(endOffset);
  const measuredStartDistance = magnitude(subtract(fromPosition, fromTarget));
  // Recover only exceptional radii whose squared norm is unsafe; ordinary orbits keep theirs.
  const recoverRadius = measuredStartDistance > SAFE_RADIUS;
  const endDirection = cameraUnitDirection(endOffset);
  const startDirection = cameraViewDirection(fromPosition, fromTarget) || endDirection;
  const cosine = Math.max(-1, Math.min(1, dot(startDirection, endDirection)));
  const tangent = unit(turningTangent(startDirection, endDirection, cosine, fromUp));
  return Object.freeze({
    position, target, fromUp, startDirection, tangent,
    rotationAxis: cross(startDirection, tangent),
    angle: Math.acos(cosine > 1 - 1e-15 ? 1 : cosine),
    startDistance: recoverRadius ? endDistance : (measuredStartDistance || endDistance),
    endDistance,
    // A small focus offset cannot be represented beside an astronomical pan target, so an
    // exceptional recovery also rebases translation; ordinary arcs stay intact.
    interpolationTarget: recoverRadius ? {x: 0, y: 0, z: 0} : fromTarget,
  });
}

export function cameraArcPose(arc, progress) {
  const theta = arc.angle * progress;
  const [c, s] = [Math.cos(theta), Math.sin(theta)];
  const distance = arc.startDistance + (arc.endDistance - arc.startDistance) * progress;
  // Large finite starts can erase node coordinates at the end by cancellation.
  const target = progress === 1 ? arc.target : mapAxes(axis => arc.interpolationTarget[axis]
    + (arc.target[axis] - arc.interpolationTarget[axis]) * progress);
  const position = progress === 1 ? arc.position
    : mapAxes(axis => target[axis] + distance * (arc.startDirection[axis] * c + arc.tangent[axis] * s));
  return {position, target, up: arc.fromUp ? turnedUp(arc, c, s) : null};
}

// A selection is seen from the focus radius, within any configured orbit bounds, along its
// direction from the origin. A positioned origin has no such direction, so the current view's is kept;
// currentDirection() is asked only for that case.
export function selectionFocusPose(target, {currentDirection, minDistance, maxDistance}) {
  if (!ARC_AXES.every(axis => Number.isFinite(target[axis]))) return null;
  const length = Math.hypot(target.x, target.y, target.z);
  if (!Number.isFinite(length)) return null;
  const distance = Math.max(minDistance ?? 0, Math.min(maxDistance ?? Infinity, FOCUS_RADIUS));
  const direction = length === 0 ? (currentDirection() || {x: 0, y: 0, z: 1}) : cameraUnitDirection(target);
  // Normalised before scaling: distance * target can underflow for a tiny non-origin node.
  const position = mapAxes(axis => target[axis] + distance * direction[axis]);
  return representable(position, target) ? {position, target} : null;
}

// A picked node is seen from the camera's current offset, so the view jumps to it unchanged.
export function pickedNodePose(target, {cameraPosition, orbitTarget}) {
  const position = mapAxes(axis => target[axis] + (cameraPosition[axis] - orbitTarget[axis]));
  return representable(position, target) ? {position, target} : null;
}

// Reliable orientation needs a finite pose whose offset has a normal-range squared length:
// finite coordinates can still lose the offset through rounding, or overflow its square.
function representable(position, target) {
  if (!ARC_AXES.every(axis => Number.isFinite(position[axis]) && Number.isFinite(target[axis]))) return false;
  const squaredOffset = ARC_AXES.reduce((sum, axis) => sum + (position[axis] - target[axis]) ** 2, 0);
  return squaredOffset >= SMALLEST_NORMAL_SQUARE && Number.isFinite(squaredOffset);
}

// Antiparallel directions need a deterministic plane across up.
function turningTangent(startDirection, endDirection, cosine, fromUp) {
  const tangent = subtract(endDirection, scale(startDirection, cosine));
  if (magnitude(tangent) >= PARALLEL) return tangent;
  for (const across of [fromUp || {x: 0, y: 1, z: 0}, {x: 1, y: 0, z: 0}, {x: 0, y: 0, z: 1}]) {
    const candidate = cross(across, startDirection);
    if (magnitude(candidate) >= PARALLEL) return candidate;
  }
  return cross({x: 0, y: 0, z: 1}, startDirection);
}

function turnedUp({rotationAxis, fromUp}, c, s) {
  const turned = cross(rotationAxis, fromUp);
  const along = dot(rotationAxis, fromUp) * (1 - c);
  return mapAxes(axis => fromUp[axis] * c + turned[axis] * s + rotationAxis[axis] * along);
}

function mapAxes(valueOf) {
  return Object.fromEntries(ARC_AXES.map(axis => [axis, valueOf(axis)]));
}

function subtract(a, b) {
  return mapAxes(axis => a[axis] - b[axis]);
}

function scale(vector, factor) {
  return mapAxes(axis => vector[axis] * factor);
}

function unit(vector) {
  return scale(vector, 1 / magnitude(vector));
}

function dot(a, b) {
  return ARC_AXES.reduce((sum, axis) => sum + a[axis] * b[axis], 0);
}

function cross(a, b) {
  return {x: a.y * b.z - a.z * b.y, y: a.z * b.x - a.x * b.z, z: a.x * b.y - a.y * b.x};
}

function magnitude(vector) {
  return Math.hypot(vector.x, vector.y, vector.z);
}
