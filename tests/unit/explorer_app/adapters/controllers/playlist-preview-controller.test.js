// Issue #138: the Preview button's command, from the current track.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {playlistPreviewController} from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/controllers/playlist-preview-controller.js';

test('Preview previews the draft from the current track', async () => {
  const previews = [];
  const controller = playlistPreviewController({playlistPreview: {preview: async trackId => previews.push(trackId)},
    currentTrackId: () => 'track-1'});
  await controller.previewRequested();
  assert.deepEqual(previews, ['track-1']);
});
