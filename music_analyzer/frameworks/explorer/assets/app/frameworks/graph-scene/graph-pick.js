// A click on a node in the 3D graph (#146). The camera moves to the node at once, keeping its offset, so the
// listener sees the pick answered before the selection is accepted.

import {pickedNodePose} from '../../domain/camera-arc.js';
import {setCameraFocusPose, settleCameraFocusInput} from './camera-focus-scene.js';

export function pickedTrackId(picked) {
  const id = picked?.id;
  return typeof id === 'string' && id ? id : null;
}

// While a replacement graph loads, a node can be visible before the vendor has it: the camera goes only where
// the vendor draws.
export function mountedPickedNode(id, {visible, mounted}) {
  if (!visible.some(node => node.id === id)) return null;
  return mounted.find(node => node.id === id) || null;
}

// The camera is best-effort: an unreachable node or a failing camera never stops the track being selected.
export function jumpCameraToPickedNode(graph, node, controlsWatch) {
  try {
    const controls = graph.controls();
    const pose = pickedNodePose({x: node.fx, y: node.fy, z: node.fz},
      {cameraPosition: graph.cameraPosition(), orbitTarget: controls.target});
    if (!pose) return 'skipped';
    controlsWatch.observe(graph);
    settleCameraFocusInput(graph);
    setCameraFocusPose(graph, pose.position, pose.target);
    return 'moved';
  } catch (error) {
    return 'failed';
  }
}
