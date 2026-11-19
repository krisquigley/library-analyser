// Issue #146: the lifecycle of one playlist download, as a state machine.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
  PLAYLIST_DOWNLOAD_STATES, PlaylistDownloadTransitionError, nextPlaylistDownloadState,
} from '../../../../music_explorer/frameworks/explorer/assets/app/domain/playlist-download.js';

test('a download starts idle and ends downloaded or failed', () => {
  assert.deepEqual(PLAYLIST_DOWNLOAD_STATES, ['idle', 'downloading', 'downloaded', 'failed']);
  assert.equal(nextPlaylistDownloadState('idle', 'start'), 'downloading');
  assert.equal(nextPlaylistDownloadState('downloading', 'succeed'), 'downloaded');
  assert.equal(nextPlaylistDownloadState('downloading', 'fail'), 'failed');
});

test('another download can start once the last one has ended', () => {
  assert.equal(nextPlaylistDownloadState('downloaded', 'start'), 'downloading');
  assert.equal(nextPlaylistDownloadState('failed', 'start'), 'downloading');
});

test('illegal transitions are rejected', () => {
  const illegal = [['downloading', 'start'], ['idle', 'succeed'], ['idle', 'fail'], ['downloaded', 'fail'],
    ['failed', 'succeed'], ['unknown', 'start']];
  for (const [state, action] of illegal) {
    assert.throws(() => nextPlaylistDownloadState(state, action),
      error => error instanceof PlaylistDownloadTransitionError
        && error.message === `A playlist download cannot ${action} while ${state}`);
  }
});
