// The BPM differences over the selected track's links (#282). Like the track labels they are text placed each drawn frame,
// here over the middle of their links, and never take pointer input, so node picking is unaffected.

export function createLinkLabels() {
  let shown = [];

  function show(host, viewModels) {
    for (const label of shown) label.remove();
    shown = viewModels.map(({sourceId, targetId, text}) => {
      const label = document.createElement('span');
      label.className = 'graph-link-label';
      label.textContent = text;
      return Object.assign(label, {sourceId, targetId});
    });
    host.append(...shown);
  }

  function place(graph, viewport, nodes) {
    if (!shown.length) return;
    const positions = new Map(nodes.map(node => [node.id, node]));
    for (const label of shown) {
      const point = linkMiddleOnScreen(graph, positions.get(label.sourceId), positions.get(label.targetId));
      label.style.transform = point ? `translate(${point.x}px,${point.y}px) translate(-50%,-50%)` : '';
      label.style.display = point && linkLabelOnScreen(point, viewport) ? '' : 'none';
    }
  }

  return Object.freeze({show, place});
}

function linkMiddleOnScreen(graph, source, target) {
  if (!source || !target) return null;
  return graph.graph2ScreenCoords((source.x + target.x) / 2, (source.y + target.y) / 2, (source.z + target.z) / 2);
}

function linkLabelOnScreen(point, viewport) {
  return Number.isFinite(point.x) && Number.isFinite(point.y) && point.x >= 0 && point.y >= 0
    && point.x < viewport.clientWidth && point.y < viewport.clientHeight;
}
