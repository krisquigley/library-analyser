// Issue #258: what the preview's play buttons and the player show for each playback event.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {presentTrackPlaybackEvent, trackPlaybackViewModel}
  from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/presenters/track-playback-presenter.js';

const PLAY = {text: '▶', verb: 'Play', pressed: false};
const PAUSE = {text: '❚❚', verb: 'Pause', pressed: true};

test('before anything plays, every button offers Play and the player is hidden', () => {
  assert.deepEqual(trackPlaybackViewModel(), {activeTrackId: null, activeButton: PLAY, idleButton: PLAY,
    status: {text: '', urgent: false}, playerShown: false});
});

test('the track loading or playing offers Pause; a paused one offers Play again', () => {
  assert.deepEqual(presentTrackPlaybackEvent({type: 'track-playback-loading', trackId: 'a'}), {activeTrackId: 'a',
    activeButton: {text: '…', verb: 'Pause', pressed: true}, idleButton: PLAY, status: {text: 'Loading the track…', urgent: false},
    playerShown: true});
  assert.deepEqual(presentTrackPlaybackEvent({type: 'track-playback-playing', trackId: 'a'}), {activeTrackId: 'a',
    activeButton: PAUSE, idleButton: PLAY, status: {text: 'Playing', urgent: false}, playerShown: true});
  assert.deepEqual(presentTrackPlaybackEvent({type: 'track-playback-paused', trackId: 'a'}), {activeTrackId: 'a',
    activeButton: PLAY, idleButton: PLAY, status: {text: 'Paused', urgent: false}, playerShown: true});
});

test('a stop hides the player; a failure says so urgently', () => {
  assert.deepEqual(presentTrackPlaybackEvent({type: 'track-playback-stopped', trackId: 'a'}), trackPlaybackViewModel());
  assert.deepEqual(presentTrackPlaybackEvent({type: 'track-playback-failed', trackId: 'a', message: 'no file'}), {activeTrackId: 'a',
    activeButton: PLAY, idleButton: PLAY, status: {text: 'Could not play the track: no file', urgent: true}, playerShown: false});
});
