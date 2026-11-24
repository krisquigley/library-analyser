// Issue #258: one track plays at a time, from the playlist preview; its lifecycle is a transitions table.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {TRACK_PLAYER_STATES, TrackPlayerTransitionError, nextTrackPlayerState, trackPlayerAllows}
  from '../../../../music_explorer/frameworks/explorer/assets/app/domain/track-player.js';

test('a track loads, plays, pauses, resumes and ends', () => {
  assert.deepEqual(TRACK_PLAYER_STATES, ['stopped', 'loading', 'playing', 'paused', 'failed']);
  const states = ['load', 'play', 'pause', 'play', 'end'].reduce((seen, action) => [...seen, nextTrackPlayerState(seen.at(-1), action)], ['stopped']);
  assert.deepEqual(states, ['stopped', 'loading', 'playing', 'paused', 'playing', 'stopped']);
});

test('another track can be loaded at any time, and a failure waits for a new load or a stop', () => {
  for (const state of TRACK_PLAYER_STATES) assert.equal(nextTrackPlayerState(state, 'load'), 'loading');
  assert.equal(nextTrackPlayerState('loading', 'fail'), 'failed');
  assert.equal(nextTrackPlayerState('failed', 'stop'), 'stopped');
  assert.equal(trackPlayerAllows('failed', 'play'), false);
});

test('an illegal step is a domain error, and what is allowed can be asked first', () => {
  assert.throws(() => nextTrackPlayerState('stopped', 'pause'), TrackPlayerTransitionError);
  assert.throws(() => nextTrackPlayerState('stopped', 'pause'), /A track cannot pause while stopped/);
  assert.deepEqual([trackPlayerAllows('stopped', 'play'), trackPlayerAllows('playing', 'pause'), trackPlayerAllows('nowhere', 'load')],
    [false, true, false]);
});
