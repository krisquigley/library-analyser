// Issue #138: the lifecycle of a playlist preview, as a transitions table.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
  PLAYLIST_PREVIEW_STATES, PlaylistPreviewTransitionError, nextPlaylistPreviewState,
} from '../../../../music_explorer/frameworks/explorer/assets/app/domain/playlist-preview.js';

test('the states of a preview', () => {
  assert.deepEqual(PLAYLIST_PREVIEW_STATES, ['idle', 'previewing', 'previewed', 'failed']);
});

test('a preview starts from any state, and only a preview in flight succeeds or fails', () => {
  const legal = [
    ['idle', 'start', 'previewing'], ['previewing', 'start', 'previewing'], ['previewed', 'start', 'previewing'],
    ['failed', 'start', 'previewing'], ['previewing', 'succeed', 'previewed'], ['previewing', 'fail', 'failed'],
  ];
  for (const [state, action, next] of legal) assert.equal(nextPlaylistPreviewState(state, action), next);
});

test('an illegal transition is refused', () => {
  for (const [state, action] of [['idle', 'succeed'], ['previewed', 'fail'], ['failed', 'succeed'], ['lost', 'start']]) {
    assert.throws(() => nextPlaylistPreviewState(state, action), PlaylistPreviewTransitionError);
  }
});
