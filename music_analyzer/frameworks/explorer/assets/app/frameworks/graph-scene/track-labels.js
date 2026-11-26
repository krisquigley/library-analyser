// The labels above the selected track and its neighbours on the screen (#243). Like the axis labels they are placed each
// drawn frame over their nodes. Only their buttons take pointer input (#276), so picking nodes elsewhere is unaffected.
// The view keeps the labels it last showed, and the playback last shown so new labels' buttons match it.

const IDLE_PLAY_BUTTON = Object.freeze({text: '▶', verb: 'Play', pressed: false});

export function createTrackLabels({onPlayRequested}) {
  let shown = [];
  let playback = null;

  function show(host, viewModels) {
    for (const label of shown) label.remove();
    shown = viewModels.map(viewModel => trackLabel(viewModel, onPlayRequested));
    host.append(...shown);
    showPlayButtons();
  }

  function showPlayback(update) {
    playback = update;
    showPlayButtons();
  }

  function showPlayButtons() {
    for (const label of shown) {
      const look = !playback ? IDLE_PLAY_BUTTON
        : label.trackId === playback.activeTrackId ? playback.activeButton : playback.idleButton;
      showPlayButton(label.playButton, look, label.trackText);
    }
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

  return Object.freeze({show, showPlayback, place});
}

function trackLabel({trackId, text, selected}, onPlayRequested) {
  const label = document.createElement('span');
  label.className = selected ? 'graph-track-label selected' : 'graph-track-label';
  const play = document.createElement('button');
  play.type = 'button';
  play.className = 'graph-track-label-play';
  play.onclick = () => onPlayRequested(trackId);
  const name = document.createElement('span');
  name.className = 'graph-track-label-text';
  name.textContent = text;
  label.append(play, name);
  return Object.assign(label, {trackId, trackText: text, playButton: play});
}

function showPlayButton(button, look, trackText) {
  button.textContent = look.text;
  button.setAttribute('aria-label', `${look.verb} ${trackText}`);
  button.setAttribute('aria-pressed', String(look.pressed));
}

function labelOnScreen(point, viewport) {
  return Number.isFinite(point.x) && Number.isFinite(point.y) && point.x >= 0 && point.y >= 0
    && point.x < viewport.clientWidth && point.y < viewport.clientHeight;
}
