// The mood axes in the 3D scene, with their labels on the screen (#146). The axes are redrawn only when their spec
// changes. The vendor bundles THREE privately, so the axes reuse the classes of a rendered node mesh: scene objects then
// share that exact THREE instance without a second dependency or global.

import {findSceneObject} from './selected-node-halo.js';

const THIN = 0.65;

export function createGraphAxes() {
  let shown = null;

  function clear() {
    if (!shown) return;
    const {group} = shown;
    group.parent.remove(group);
    for (const mesh of group.children) { mesh.geometry.dispose(); mesh.material.dispose(); }
    for (const label of group.labels) label.remove();
    shown = null;
  }

  function sync(graph, spec, labelHost) {
    const signature = JSON.stringify(spec);
    if (shown && shown.graph === graph && shown.signature === signature) return shown.group;
    clear();
    if (!spec.length) return null;
    const scene = graph.scene();
    // Node objects may arrive one frame after graphData().
    const sample = findSceneObject(scene, object => object.__graphObjType === 'node' && object.geometry && object.material);
    if (!sample) return null;
    const group = new scene.constructor();
    group.name = 'mood-xyz-axes';
    group.labels = [];
    for (const axis of spec) {
      group.add(axisMesh(sample, axis));
      if (labelHost) group.labels.push(...axisLabels(axis, labelHost));
    }
    scene.add(group);
    shown = {graph, signature, group};
    return group;
  }

  function placeLabels(graph, viewport) {
    for (const label of shown?.group.labels || []) {
      const {x, y, z} = label.axisPosition;
      const point = graph.graph2ScreenCoords(x, y, z);
      label.style.transform = `translate(${point.x}px,${point.y}px) translate(-50%,-50%)`;
      label.style.display = onScreen(point, viewport) ? '' : 'none';
    }
  }

  return Object.freeze({sync, placeLabels});
}

function axisMesh(sample, axis) {
  const mesh = new sample.constructor(new sample.geometry.constructor(1, 8, 6),
    new sample.material.constructor({color: axis.color, transparent: true, opacity: 0.8, depthWrite: false}));
  mesh.name = 'axis-' + axis.key;
  mesh.raycast = () => {}; // Not a track or a link, so never eligible for graph picking.
  const length = axis.end[axis.key] - axis.start[axis.key];
  const center = {...axis.start, [axis.key]: axis.start[axis.key] + length / 2};
  mesh.position.set(center.x, center.y, center.z);
  const reach = key => (axis.key === key ? length / 2 : THIN);
  mesh.scale.set(reach('x'), reach('y'), reach('z'));
  return mesh;
}

function axisLabels(axis, host) {
  return [[axis.label, axis.end], ['data ' + axis.references.join('–'), axis.start]].map(([content, position]) => {
    const label = document.createElement('span');
    label.className = 'graph-axis-label';
    label.textContent = content;
    label.style.color = axis.color;
    label.axisPosition = position;
    host.append(label);
    return label;
  });
}

function onScreen(point, viewport) {
  return Number.isFinite(point.x) && Number.isFinite(point.y) && point.x >= 0 && point.y >= 0
    && point.x < viewport.clientWidth && point.y < viewport.clientHeight;
}
