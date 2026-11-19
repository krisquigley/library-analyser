// Issue #146: the current track's lifecycle, from the listener's choice to its detail on screen.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
  TRACK_SELECTION_STATES, TrackSelectionTransitionError, awaitingServer, nextTrackSelectionState,
} from '../../../../music_explorer/frameworks/explorer/assets/app/domain/track-selection.js';

const SETTLED = ['none', 'shown', 'detail-failed', 'refused'];

test('the states are the selection lifecycle', () => {
  assert.deepEqual(TRACK_SELECTION_STATES,
    ['none', 'choosing', 'rewinding', 'loading-detail', 'shown', 'detail-failed', 'refused']);
});

test('a choice or an undo/reset can start from any state, and replaces whatever was in flight', () => {
  for (const state of TRACK_SELECTION_STATES) {
    assert.equal(nextTrackSelectionState(state, 'choose'), 'choosing', state);
    assert.equal(nextTrackSelectionState(state, 'rewind'), 'rewinding', state);
  }
});

test('the server accepting a track loads its detail; accepting no track settles on none', () => {
  for (const state of ['choosing', 'rewinding']) {
    assert.equal(nextTrackSelectionState(state, 'accept-track'), 'loading-detail');
    assert.equal(nextTrackSelectionState(state, 'accept-none'), 'none');
    assert.equal(nextTrackSelectionState(state, 'refuse'), 'refused');
  }
});

test('a detail load ends shown or failed, or gives way to the library state naming another track or none', () => {
  assert.equal(nextTrackSelectionState('loading-detail', 'show-detail'), 'shown');
  assert.equal(nextTrackSelectionState('loading-detail', 'fail-detail'), 'detail-failed');
  assert.equal(nextTrackSelectionState('loading-detail', 'load-detail'), 'loading-detail');
  assert.equal(nextTrackSelectionState('loading-detail', 'clear'), 'none');
});

test('a settled selection can reload its detail, or learn from the library state', () => {
  for (const state of SETTLED) {
    assert.equal(nextTrackSelectionState(state, 'load-detail'), 'loading-detail', state);
    assert.equal(nextTrackSelectionState(state, 'clear'), 'none', state);
  }
});

test('anything else is refused as a domain error', () => {
  assert.throws(() => nextTrackSelectionState('none', 'show-detail'), TrackSelectionTransitionError);
  assert.throws(() => nextTrackSelectionState('shown', 'accept-track'), /cannot accept-track while shown/);
  assert.throws(() => nextTrackSelectionState('choosing', 'load-detail'), TrackSelectionTransitionError);
  assert.throws(() => nextTrackSelectionState('loading-detail', 'refuse'), TrackSelectionTransitionError);
  assert.throws(() => nextTrackSelectionState('lost', 'choose'), TrackSelectionTransitionError);
});

test('a selection awaits the server while choosing or rewinding', async () => {

  assert.deepEqual(TRACK_SELECTION_STATES.filter(awaitingServer), ['choosing', 'rewinding']);
});
