// The ▶ button on a playlist table's row (#258), shared by the playlist preview and the hand-built playlist (#287).
// It plays the track it names; the track playing has the active look, every other the idle one.

const IDLE_TRACK_PLAY = Object.freeze({text: '▶', verb: 'Play', pressed: false});

export function trackPlayButton({trackId, trackName}, onPlayRequested) {
  const button = Object.assign(document.createElement('button'), {type: 'button', className: 'track-play'});
  Object.assign(button.dataset, {trackId, trackName});
  button.onclick = () => onPlayRequested(trackId);
  showTrackPlayLook(button, IDLE_TRACK_PLAY);
  return button;
}

export function showTrackPlayButton(button, playback) {
  if (!playback) return;
  showTrackPlayLook(button, button.dataset.trackId === playback.activeTrackId ? playback.activeButton : playback.idleButton);
}

function showTrackPlayLook(button, look) {
  button.textContent = look.text;
  button.setAttribute('aria-label', `${look.verb} ${button.dataset.trackName}`);
  button.setAttribute('aria-pressed', String(look.pressed));
}
