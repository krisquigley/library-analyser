// The library graph's status panel (#146), with its reload or retry button and, once ready, the playlist controls.
// While the graph stays ready only the message is replaced, so the playlist controls keep their live state.

export function graphStatusView({onReload, appendPlaylistControls}) {
  function show({status, message}) {
    const panel = graphStatusPanel();
    if (!panel) return;
    const signature = JSON.stringify([status, message]);
    if (panel.dataset.graphStatusSignature === signature) return;
    if (status === 'ready' && panel.dataset.graphLoadStatus === 'ready') {
      panel.replaceChild(setGraphStatusText(document.createElement('p'), message), panel.children[1]);
      panel.dataset.graphStatusSignature = signature;
      return;
    }
    panel.replaceChildren();
    panel.append(setGraphStatusText(document.createElement('h3'), 'Library graph'), graphStatusMessageElement(status, message));
    if (status === 'error' || status === 'ready') panel.append(graphReloadButton(status, onReload));
    if (status === 'ready') appendPlaylistControls(panel);
    else if (status === 'loading' || status === 'rendering') panel.append(graphBusyElement(status));
    panel.dataset.graphStatusSignature = signature;
    panel.dataset.graphLoadStatus = status;
  }

  return Object.freeze({show});
}

function graphStatusPanel() {
  const root = document.getElementById('graph-load-status') || document.getElementById('controls');
  if (!root) return null;
  let panel = document.getElementById('graph-load-status');
  if (!panel) {
    panel = document.createElement('section');
    panel.id = 'graph-load-status';
    panel.className = 'graph-load-status';
    root.append(panel);
  }
  return panel;
}

function graphStatusMessageElement(status, message) {
  const paragraph = document.createElement('p');
  if (status === 'error') {
    paragraph.setAttribute('role', 'alert');
    paragraph.setAttribute('aria-live', 'assertive');
  }
  return setGraphStatusText(paragraph, message);
}

function graphReloadButton(status, onReload) {
  const button = document.createElement('button');
  button.id = status === 'error' ? 'retry-graph' : 'reload-graph';
  button.type = 'button';
  setGraphStatusText(button, status === 'error' ? 'Retry graph' : 'Reload graph');
  button.onclick = () => onReload();
  return button;
}

function graphBusyElement(status) {
  const busy = document.createElement('p');
  busy.setAttribute('role', 'status');
  busy.setAttribute('aria-live', 'polite');
  return setGraphStatusText(busy, status === 'loading' ? 'Loading graph…' : 'Rendering graph…');
}

function setGraphStatusText(element, value) {
  element.textContent = value == null ? '' : String(value);
  return element;
}
