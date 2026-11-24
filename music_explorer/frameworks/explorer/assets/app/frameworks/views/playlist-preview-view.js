// The playlist preview in the page (#138): a Preview button, its status, the energy chart and the list of tracks.
// #258: each track has a Play button, and one audio player, with its own seek bar, plays the track asked for.
// It keeps only the elements it last mounted, and the playback last shown so new rows' buttons match it.

const TARGET_LINE = Object.freeze({color: '#8dd6ff', dash: Object.freeze([4, 3])});
const LEVEL_LINE = Object.freeze({color: '#ffcf70', dash: Object.freeze([])});
const PREVIEW_COLUMNS = Object.freeze([
  ['place', '#'], ['track', 'Track'], ['length', 'Length'], ['bpm', 'BPM'], ['key', 'Key'], ['energy', 'Energy'], ['target', 'Target'],
  ['transition', 'Transition']]);

export function playlistPreviewView({onPreviewRequested, onPlayRequested, player}) {
  let mounted = null;
  let busy = false;
  let ready = true;
  let playback = null;

  function show(update) {
    if (!mounted) return;
    if (update.previewDisabled !== undefined) busy = update.previewDisabled;
    if (update.readiness) {
      ready = update.readiness.ready;
      mounted.reason.textContent = update.readiness.reason;
    }
    mounted.button.disabled = busy || !ready;
    if (update.status) showStatus(mounted.status, update.status);
    if (update.rows) {
      mounted.body.replaceChildren(...update.rows.map(row => previewRow(row, onPlayRequested)));
      showPlayButtons(mounted.body, playback);
    }
    if (update.chart) drawEnergyChart(mounted.chart, update.chart);
  }

  function showPlayback(update) {
    playback = update;
    if (!mounted) return;
    showPlayButtons(mounted.body, playback);
    player.hidden = !playback.playerShown;
    showStatus(mounted.playerStatus, playback.status);
  }

  function mount(panel, viewModel) {
    const button = element('button', {id: 'preview-playlist', type: 'button', textContent: 'Preview'});
    button.onclick = () => onPreviewRequested();
    const reason = element('p', {id: 'playlist-preview-reason', className: 'playlist-preview-reason'});
    button.setAttribute('aria-describedby', reason.id);
    const status = element('p', {id: 'playlist-preview-status', className: 'muted'});
    Object.assign(player, {id: 'playlist-track-player', className: 'playlist-track-player', controls: true, preload: 'none'});
    player.setAttribute('aria-label', 'Track player');
    const playerStatus = element('p', {id: 'playlist-player-status', className: 'muted'});
    const chart = element('canvas', {id: 'playlist-energy-chart', className: 'playlist-energy-chart'});
    chart.setAttribute('role', 'img');
    const heading = element('tr', {id: 'playlist-preview-heading'});
    heading.append(element('th', {scope: 'col', textContent: 'Play'}), ...PREVIEW_COLUMNS.map(([, caption]) => element('th', {scope: 'col', textContent: caption})));
    const head = element('thead', {});
    head.append(heading);
    const body = element('tbody', {id: 'playlist-preview-tracks'});
    const table = element('table', {className: 'playlist-preview-table'});
    table.append(head, body);
    const section = element('section', {id: 'playlist-preview'});
    section.setAttribute('aria-label', 'Playlist preview');
    section.append(button, reason, status, player, playerStatus, chart, table);
    panel.append(section);
    mounted = {button, reason, status, playerStatus, chart, body};
    show(viewModel);
    showPlayback(viewModel.playback);
  }

  return Object.freeze({mount, show, showPlayback});
}

function drawEnergyChart(canvas, chart) {
  canvas.width = chart.width;
  canvas.height = chart.height;
  canvas.setAttribute('aria-label', chart.label);
  const context = canvas.getContext('2d');
  context.clearRect(0, 0, chart.width, chart.height);
  context.lineWidth = 2;
  drawLine(context, chart.target, TARGET_LINE);
  drawLine(context, chart.level, LEVEL_LINE);
}

function drawLine(context, segments, {color, dash}) {
  context.strokeStyle = color;
  context.setLineDash([...dash]);
  for (const [[x, y], ...rest] of segments) {
    context.beginPath();
    context.moveTo(x, y);
    for (const [nextX, nextY] of rest) context.lineTo(nextX, nextY);
    context.stroke();
  }
}

function previewRow(row, onPlayRequested) {
  const play = element('button', {type: 'button', className: 'track-play'});
  Object.assign(play.dataset, {trackId: row.trackId, trackName: row.track});
  play.onclick = () => onPlayRequested(row.trackId);
  const playCell = element('td', {className: 'track-play-cell'});
  playCell.append(play);
  const line = element('tr', {});
  line.append(playCell, ...PREVIEW_COLUMNS.map(([field]) => element('td', {textContent: row[field]})));
  return line;
}

function showPlayButtons(body, playback) {
  if (!playback) return;
  for (const line of body.children) {
    const play = line.children[0].children[0];
    const look = play.dataset.trackId === playback.activeTrackId ? playback.activeButton : playback.idleButton;
    play.textContent = look.text;
    play.setAttribute('aria-label', `${look.verb} ${play.dataset.trackName}`);
    play.setAttribute('aria-pressed', String(look.pressed));
  }
}

function showStatus(status, {text, urgent}) {
  status.setAttribute('role', urgent ? 'alert' : 'status');
  status.setAttribute('aria-live', urgent ? 'assertive' : 'polite');
  status.textContent = text;
}

function element(tag, properties) {
  return Object.assign(document.createElement(tag), properties);
}
