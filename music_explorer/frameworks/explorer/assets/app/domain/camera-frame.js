// Framing the graph for the camera (#146). Only display coordinates are framed:
// musical-axis values and fixed node positions are never changed.

const FRAMED_AXES = Object.freeze(['x', 'y', 'z']);
const DEFAULT_FIELD_OF_VIEW = 50;
const FRAMED_NODE_RADIUS = 4;
const FRAME_PADDING = 1.2;
const CLOSEST_DISTANCE = 40;
const EMPTY_FRAME_DISTANCE = 650;

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
  const aspect = size.width > 0 && size.height > 0 ? size.width / size.height : 1;
  const usableFieldOfView = Number.isFinite(fieldOfView) && fieldOfView > 0 && fieldOfView < 180 ? fieldOfView : DEFAULT_FIELD_OF_VIEW;
  const tanHalfFov = Math.tan(usableFieldOfView * Math.PI / 360);
  const fit = Math.max((half.y + FRAMED_NODE_RADIUS) / tanHalfFov, (half.x + FRAMED_NODE_RADIUS) / (tanHalfFov * aspect));
  const distance = Math.max(CLOSEST_DISTANCE, half.z + FRAMED_NODE_RADIUS + FRAME_PADDING * fit);
  return {position: {x: target.x, y: target.y, z: target.z + distance}, target};
}
