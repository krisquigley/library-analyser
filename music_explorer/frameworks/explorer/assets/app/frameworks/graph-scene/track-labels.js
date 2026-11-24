// The labels above the selected track and its neighbours on the screen (#243). Like the axis labels they are text,
// placed each drawn frame over their nodes, and never take pointer input, so node picking is unaffected.

export function createTrackLabels() {
  let shown = [];

  function show(host, viewModels) {
    for (const label of shown) label.remove();
    shown = viewModels.map(({trackId, text, selected}) => {
      const label = document.createElement('span');
      label.className = selected ? 'graph-track-label selected' : 'graph-track-label';
      label.textContent = text;
      label.trackId = trackId;
      host.append(label);
      return label;
    });
  }

  function place(graph, viewport, nodes) {
    if (!shown.length) return;
    const positions = new Map(nodes.map(node => [node.id, node]));
    for (const label of shown) {
      const node = positions.get(label.trackId);
      const point = node ? graph.graph2ScreenCoords(node.x, node.y, node.z) : null;
      label.style.transform = point ? `translate(${point.x}px,${point.y}px) translate(-50%,calc(-100% - 10px))` : '';
      label.style.display = point && labelOnScreen(point, viewport) ? '' : 'none';
    }
  }

  return Object.freeze({show, place});
}

function labelOnScreen(point, viewport) {
  return Number.isFinite(point.x) && Number.isFinite(point.y) && point.x >= 0 && point.y >= 0
    && point.x < viewport.clientWidth && point.y < viewport.clientHeight;
}
