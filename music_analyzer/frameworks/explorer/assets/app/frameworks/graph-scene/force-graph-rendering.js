// The 3D graph's drawing loop in the page (#86, #146): the vendor's public animation API, the pose of the view,
// and the input that wakes it.

export function forceGraphRenderer(currentGraph) {
  return Object.freeze({
    canPause: () => typeof currentGraph()?.pauseAnimation === 'function',
    pause: () => currentGraph()?.pauseAnimation?.(),
    resume: () => currentGraph()?.resumeAnimation?.(),
  });
}

// Programmatic camera moves (tests, tools, vendor helpers) bypass input events, so the pose itself is compared.
export function graphViewPose(graph) {
  const camera = graph.camera?.();
  const controls = graph.controls?.();
  const vector = point => (point ? [point.x, point.y, point.z, point.w] : null);
  return JSON.stringify([vector(camera?.position), vector(camera?.quaternion), vector(camera?.up), vector(controls?.target)]);
}

// The controls and hover picking update only inside the vendor loop, so their input must wake it.
export function observeGraphInput(element, onInput) {
  if (typeof element?.addEventListener !== 'function') return;
  for (const type of ['pointerdown', 'pointermove', 'wheel']) element.addEventListener(type, () => onInput(), {capture: true, passive: true});
}
