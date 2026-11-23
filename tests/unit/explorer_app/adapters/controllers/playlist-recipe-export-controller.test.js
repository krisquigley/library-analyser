// Issue #139: the Export recipe button's command, from the current track.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {playlistRecipeExportController} from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/controllers/playlist-recipe-export-controller.js';

test('Export recipe exports the draft from the current track', () => {
  const exported = [];
  const controller = playlistRecipeExportController({playlistRecipeExport: {exportRecipe: id => exported.push(id)},
    currentTrackId: () => 'track-1'});
  controller.exportRequested();
  assert.deepEqual(exported, ['track-1']);
});
