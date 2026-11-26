// The strip over the graph that lists the hand-built playlist (#278): its tracks in order, each with a button to remove
// it, and Clear and Download M3U. It renders view models and reports the listener's input; it keeps only the elements it
// built, to update them in place.

export function handBuiltPlaylistView({onRemoveRequested, onClearRequested, onDownloadRequested}) {
  let built = null;

  function strip() {
    const host = document.getElementById('hand-built-playlist');
    if (host && !built) built = buildStrip(host, {onClearRequested, onDownloadRequested});
    return built;
  }

  function show(viewModel) {
    const parts = strip();
    if (!parts) return;
    parts.host.hidden = viewModel.hidden;
    parts.heading.textContent = viewModel.heading;
    parts.tracks.replaceChildren(...viewModel.rows.map(row => stripTrackRow(row, onRemoveRequested)));
    parts.clear.disabled = viewModel.clearDisabled;
    parts.download.disabled = viewModel.downloadDisabled;
    showStripStatus(parts.status, viewModel.notice);
  }

  function showDownload(status) {
    const parts = strip();
    if (parts) showStripStatus(parts.status, status);
  }

  return Object.freeze({show, showDownload});
}

function buildStrip(host, {onClearRequested, onDownloadRequested}) {
  const heading = stripElement('h2', {id: 'hand-built-playlist-heading'});
  const tracks = stripElement('ol', {id: 'hand-built-playlist-tracks', className: 'hand-built-playlist-tracks'});
  const clear = stripElement('button', {id: 'hand-built-playlist-clear', type: 'button', textContent: 'Clear'});
  clear.onclick = () => onClearRequested();
  const download = stripElement('button', {id: 'hand-built-playlist-download', type: 'button', textContent: 'Download M3U'});
  download.onclick = () => onDownloadRequested();
  const actions = stripElement('div', {className: 'hand-built-playlist-actions'});
  actions.append(clear, download);
  const status = stripElement('p', {id: 'hand-built-playlist-status', className: 'muted'});
  host.replaceChildren(heading, tracks, actions, status);
  return {host, heading, tracks, clear, download, status};
}

function stripTrackRow({trackId, text, removeLabel}, onRemoveRequested) {
  const row = stripElement('li', {});
  const remove = stripElement('button', {type: 'button', className: 'hand-built-playlist-remove', textContent: '×'});
  remove.setAttribute('aria-label', removeLabel);
  remove.onclick = () => onRemoveRequested(trackId);
  row.append(stripElement('span', {textContent: text}), remove);
  return row;
}

function showStripStatus(status, {text, urgent}) {
  status.setAttribute('role', urgent ? 'alert' : 'status');
  status.setAttribute('aria-live', urgent ? 'assertive' : 'polite');
  status.textContent = text;
}

function stripElement(tag, properties) {
  return Object.assign(document.createElement(tag), properties);
}
