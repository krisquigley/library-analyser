// Framing the graph for the camera (#146). Only display coordinates are framed:
// musical-axis values and fixed node positions are never changed.

const FRAMED_AXES = Object.freeze(['x', 'y', 'z']);
const DEFAULT_FIELD_OF_VIEW = 50;
const FRAMED_NODE_RADIUS = 4;
const FRAME_PADDING = 1.2;
const CLOSEST_DISTANCE = 40;
const EMPTY_FRAME_DISTANCE = 650;
// The selection's focus radius: closer, the enlarged selected node and its halo crowd out its neighbours.
const CLOSEST_SELECTION_DISTANCE = 100;

// #267: how far a selection is seen from, looking along a unit direction (from the selection towards the camera),
// so every neighbour fits the narrower field of view of this viewport. A neighbour is measured as the camera sees it:
// its sideways offset from the line of sight, at its own depth. Null when no neighbour is positioned.
export function neighbourhoodCameraDistance(centre, neighbours, {direction, size, fieldOfView}) {
  const offsets = neighbours.filter(node => FRAMED_AXES.every(axis => Number.isFinite(node[axis])))
    .map(node => mapFramedAxes(axis => node[axis] - centre[axis]));
  if (!offsets.length) return null;
  const tanHalfFov = Math.tan(usableFieldOfView(fieldOfView) * Math.PI / 360) * Math.min(1, viewportAspect(size));
  const needed = offsets.map(offset => {
    const depth = FRAMED_AXES.reduce((sum, axis) => sum + offset[axis] * direction[axis], 0);
    const sideways = Math.hypot(...FRAMED_AXES.map(axis => offset[axis] - depth * direction[axis]));
    return depth + FRAME_PADDING * (sideways + FRAMED_NODE_RADIUS) / tanHalfFov;
  });
  return Math.max(CLOSEST_SELECTION_DISTANCE, ...needed);
}

function mapFramedAxes(valueOf) {
  return Object.fromEntries(FRAMED_AXES.map(axis => [axis, valueOf(axis)]));
}

function viewportAspect(size) {
  return size.width > 0 && size.height > 0 ? size.width / size.height : 1;
}

function usableFieldOfView(fieldOfView) {
  return Number.isFinite(fieldOfView) && fieldOfView > 0 && fieldOfView < 180 ? fieldOfView : DEFAULT_FIELD_OF_VIEW;
}

export function graphCameraFrame(nodes, size, fieldOfView) {
  const positioned = nodes.filter(node => FRAMED_AXES.every(axis => Number.isFinite(node[axis])));
  if (!positioned.length) return {position: {x: 0, y: 0, z: EMPTY_FRAME_DISTANCE}, target: {x: 0, y: 0, z: 0}};
  const target = {};
  const half = {};
  for (const axis of FRAMED_AXES) {
    const values = positioned.map(node => node[axis]);
    const [min, max] = [Math.min(...values), Math.max(...values)];
    target[axis] = (min + max) / 2;
    half[axis] = (max - min) / 2;
  }
  const aspect = viewportAspect(size);
  const tanHalfFov = Math.tan(usableFieldOfView(fieldOfView) * Math.PI / 360);
  const fit = Math.max((half.y + FRAMED_NODE_RADIUS) / tanHalfFov, (half.x + FRAMED_NODE_RADIUS) / (tanHalfFov * aspect));
  const distance = Math.max(CLOSEST_DISTANCE, half.z + FRAMED_NODE_RADIUS + FRAME_PADDING * fit);
  return {position: {x: target.x, y: target.y, z: target.z + distance}, target};
}
