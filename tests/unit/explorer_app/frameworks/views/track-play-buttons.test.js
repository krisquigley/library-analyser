// Issues #258, #287: the ▶ button a playlist table's row has, shared by the preview and the hand-built playlist.
import {test, beforeEach} from 'node:test';
import assert from 'node:assert/strict';
import {showTrackPlayButton, trackPlayButton} from '../../../../../music_explorer/frameworks/explorer/assets/app/frameworks/views/track-play-buttons.js';
import {installFakeDocument} from '../fake-document.js';

beforeEach(() => { installFakeDocument([]); });

const look = button => [button.textContent, button.getAttribute('aria-label'), button.getAttribute('aria-pressed')];

test('a play button names its track, starts idle, and asks for its track', () => {
  const asked = [];
  const button = trackPlayButton({trackId: 'a', trackName: 'Synthetic – Alpha'}, trackId => asked.push(trackId));
  assert.deepEqual([button.tagName, button.type, button.className, button.dataset.trackId], ['BUTTON', 'button', 'track-play', 'a']);
  assert.deepEqual(look(button), ['▶', 'Play Synthetic – Alpha', 'false']);
  button.onclick();
  assert.deepEqual(asked, ['a']);
});

test('the playing track has the active look and every other the idle one; no playback changes nothing', () => {
  const playback = {activeTrackId: 'a', activeButton: {text: '❚❚', verb: 'Pause', pressed: true},
    idleButton: {text: '▶', verb: 'Play', pressed: false}};
  const [a, b] = ['a', 'b'].map(trackId => trackPlayButton({trackId, trackName: trackId.toUpperCase()}, () => {}));
  showTrackPlayButton(a, null);
  assert.deepEqual(look(a), ['▶', 'Play A', 'false']);
  for (const button of [a, b]) showTrackPlayButton(button, playback);
  assert.deepEqual([look(a), look(b)], [['❚❚', 'Pause A', 'true'], ['▶', 'Play B', 'false']]);
});
