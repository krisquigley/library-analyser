// The strip over the graph that lists the hand-built playlist (#278), as a table like the playlist preview's (#287):
// each track with ▶ to play it and a button to remove it, then Clear and Download M3U. It renders view models and
// reports the listener's input; it keeps only the elements it built, to update them in place, and the playback last
// shown so new rows' buttons match it.

import {showTrackPlayButton, trackPlayButton} from './track-play-buttons.js';

const STRIP_COLUMNS = Object.freeze([
  ['place', '#'], ['track', 'Track'], ['length', 'Length'], ['bpm', 'BPM'], ['key', 'Key'], ['energy', 'Energy'],
  ['transition', 'Transition']]);

export function handBuiltPlaylistView({onRemoveRequested, onClearRequested, onDownloadRequested, onPlayRequested}) {
  let built = null;
  let playback = null;

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
    parts.tracks.replaceChildren(...viewModel.rows.map(row => stripTrackRow(row, {onRemoveRequested, onPlayRequested})));
    showStripPlayback(parts.tracks, playback);
    parts.clear.disabled = viewModel.clearDisabled;
    parts.download.disabled = viewModel.downloadDisabled;
    showStripStatus(parts.status, viewModel.notice);
  }

  function showPlayback(update) {
    playback = update;
    const parts = strip();
    if (parts) showStripPlayback(parts.tracks, playback);
  }

  function showDownload(status) {
    const parts = strip();
    if (parts) showStripStatus(parts.status, status);
  }

  return Object.freeze({show, showPlayback, showDownload});
}

function buildStrip(host, {onClearRequested, onDownloadRequested}) {
  const heading = stripElement('h2', {id: 'hand-built-playlist-heading'});
  const headings = stripElement('tr', {});
  headings.append(...['Play', ...STRIP_COLUMNS.map(([, caption]) => caption), 'Remove']
    .map(caption => stripElement('th', {scope: 'col', textContent: caption})));
  const head = stripElement('thead', {});
  head.append(headings);
  const tracks = stripElement('tbody', {id: 'hand-built-playlist-tracks'});
  const table = stripElement('table', {className: 'playlist-preview-table hand-built-playlist-table'});
  table.append(head, tracks);
  const scroller = stripElement('div', {className: 'hand-built-playlist-tracks'});
  scroller.append(table);
  const clear = stripElement('button', {id: 'hand-built-playlist-clear', type: 'button', textContent: 'Clear'});
  clear.onclick = () => onClearRequested();
  const download = stripElement('button', {id: 'hand-built-playlist-download', type: 'button', textContent: 'Download M3U'});
  download.onclick = () => onDownloadRequested();
  const actions = stripElement('div', {className: 'hand-built-playlist-actions'});
  actions.append(clear, download);
  const status = stripElement('p', {id: 'hand-built-playlist-status', className: 'muted'});
  host.replaceChildren(heading, scroller, actions, status);
  return {host, heading, tracks, clear, download, status};
}

function stripTrackRow(row, {onRemoveRequested, onPlayRequested}) {
  const play = trackPlayButton({trackId: row.trackId, trackName: row.track}, onPlayRequested);
  play.disabled = !row.playable;
  const remove = stripElement('button', {type: 'button', className: 'hand-built-playlist-remove', textContent: '×'});
  remove.setAttribute('aria-label', row.removeLabel);
  remove.onclick = () => onRemoveRequested(row.trackId);
  const line = stripElement('tr', {});
  line.append(stripCell(play, 'track-play-cell'), ...STRIP_COLUMNS.map(([field]) => stripElement('td', {textContent: row[field]})),
    stripCell(remove, 'hand-built-playlist-remove-cell'));
  return line;
}

function stripCell(content, className) {
  const cell = stripElement('td', {className});
  cell.append(content);
  return cell;
}

function showStripPlayback(tracks, playback) {
  for (const line of tracks.children) showTrackPlayButton(line.children[0].children[0], playback);
}

function showStripStatus(status, {text, urgent}) {
  status.setAttribute('role', urgent ? 'alert' : 'status');
  status.setAttribute('aria-live', urgent ? 'assertive' : 'polite');
  status.textContent = text;
}

function stripElement(tag, properties) {
  return Object.assign(document.createElement(tag), properties);
}
