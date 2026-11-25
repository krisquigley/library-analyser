// The 3D graph in the page (#146): the vendor graph's configuration, its size, the data it is handed, the camera
// framing of a new layout, and the flat canvas drawn where WebGL is unavailable.

import {graphCameraFrame} from '../../domain/camera-frame.js';
import {setCameraFocusPose} from './camera-focus-scene.js';

const DEFAULT_GRAPH_SIZE = Object.freeze({width: 900, height: 1040});
const PANEL_TRIM = Object.freeze(['paddingLeft', 'paddingRight', 'borderLeftWidth', 'borderRightWidth']);

// Positions are fixed by the mood axes: no dragging, no simulation, and link opacity comes from each link's colour.
export function configureForceGraph(graph, {nodeLabel, linkLabel, linkColor, linkWidth, nodeValue, onNodeClick}) {
  return graph.enableNodeDrag(false).cooldownTicks(0).nodeId('id').nodeRelSize(4).nodeLabel(nodeLabel)
    .nodeColor(node => node.color).nodeVal(nodeValue).linkLabel(linkLabel).linkOpacity(1).linkColor(linkColor)
    .linkWidth(linkWidth).onNodeClick(onNodeClick);
}

// Selection changes the node's size, never its colour, which belongs to its mood.
export function selectedTrackNodeSize(currentTrackId) {
  return node => (node.id === currentTrackId() ? 4 : 1);
}

export function graphDimensions(element) {
  const parent = element && element.parentElement;
  const style = parent && typeof getComputedStyle === 'function' ? getComputedStyle(parent) : null;
  const trim = style ? PANEL_TRIM.reduce((sum, name) => sum + (parseFloat(style[name]) || 0), 0) : 0;
  const width = Math.max(1, Math.floor(((parent && parent.clientWidth) || element.clientWidth || DEFAULT_GRAPH_SIZE.width) - trim));
  const height = Math.max(1, Math.floor(element.clientHeight || DEFAULT_GRAPH_SIZE.height));
  return {width, height};
}

export function fitGraphToElement(graph, element) {
  const size = graphDimensions(element);
  graph.width(size.width).height(size.height);
  return size;
}

// The element, its panel and the window can each change the graph's room.
export function observeElementResize(element, onResize) {
  if (typeof ResizeObserver !== 'undefined') {
    const observer = new ResizeObserver(onResize);
    observer.observe(element);
    if (element.parentElement) observer.observe(element.parentElement);
  }
  if (typeof window !== 'undefined') window.addEventListener('resize', onResize);
}

export function graphContainer() {
  const existing = document.getElementById('graph3d');
  if (existing) return existing;
  const container = document.createElement('div');
  container.id = 'graph3d';
  document.getElementById('map')?.replaceWith(container);
  return container;
}

// Handing the vendor new data restarts its scene, so it is done only when the nodes or links change; otherwise the
// nodes already shown take the new mood scores and axes. It keeps only the data it last handed over.
export function createGraphDataMount({onReplaced}) {
  let mounted = {nodes: [], links: []};
  let signature = null;

  function mount(graph, data) {
    const next = JSON.stringify([data.nodes.map(node => [node.id, node.x, node.y, node.z]),
      data.links.map(link => [link.source, link.target, link.score])]);
    if (next !== signature) {
      onReplaced();
      mounted = {nodes: data.nodes.map(node => ({...node, fx: node.fx, fy: node.fy, fz: node.fz})),
        links: data.links.map(link => ({...link}))};
      graph.graphData(mounted);
      signature = next;
    } else {
      refreshShownNodes(data.nodes);
    }
    graph.numDimensions(3);
    graph.d3AlphaDecay(1);
    graph.d3VelocityDecay(1);
  }

  function refreshShownNodes(nodes) {
    const live = new Map(nodes.map(node => [node.id, node]));
    for (const node of mounted.nodes) {
      const updated = live.get(node.id);
      if (updated) Object.assign(node, {moodScore: updated.moodScore, axis: updated.axis});
    }
  }

  return Object.freeze({mount, current: () => mounted});
}

// A new layout is framed once; a refresh, a filter that keeps the layout, or a resize keeps the listener's view.
export function createGraphFraming({onReframe}) {
  let framed = null;

  function frame(graph, nodes, size) {
    const layout = JSON.stringify(nodes.map(node => JSON.stringify([node.id, node.x, node.y, node.z])).sort());
    if (layout === framed) return;
    const {position, target} = graphCameraFrame(nodes, size, graph.camera().fov);
    onReframe();
    setCameraFocusPose(graph, position, target);
    framed = layout;
  }

  return Object.freeze({frame, layout: () => framed});
}

export function drawCanvasFallback(data, container, currentTrackId) {
  const canvas = fallbackCanvas(container);
  const size = graphDimensions(canvas);
  canvas.width = size.width;
  canvas.height = size.height;
  const context = canvas.getContext('2d');
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.fillStyle = '#fafafa';
  context.fillRect(0, 0, canvas.width, canvas.height);
  for (const node of data.nodes) {
    context.beginPath();
    context.arc(canvas.width / 2 + node.fx, canvas.height / 2 - node.fy, node.id === currentTrackId ? 9 : 5, 0, Math.PI * 2);
    context.fillStyle = node.color;
    context.fill();
  }
}

function fallbackCanvas(container) {
  const existing = document.getElementById('map');
  if (existing) return existing;
  if (!container) return document.createElement('canvas');
  const canvas = (container.children || []).find(child => child.tagName === 'CANVAS') || document.createElement('canvas');
  canvas.id = 'map';
  if (!canvas.parentElement) {
    if (typeof container.replaceChildren === 'function') container.replaceChildren(canvas);
    else container.append?.(canvas);
  }
  return canvas;
}
