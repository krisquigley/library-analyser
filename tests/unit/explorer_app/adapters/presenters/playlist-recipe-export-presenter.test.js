// Issue #139: what the listener is told after exporting a recipe.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {presentPlaylistRecipeExportEvent} from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/presenters/playlist-recipe-export-presenter.js';

test('an export names the file and how to save it; a failure is an alert', () => {
  assert.deepEqual(presentPlaylistRecipeExportEvent({type: 'playlist-recipe-exported', filename: 'playlist-recipe.json'}),
    {status: {text: 'Recipe exported as playlist-recipe.json. Save it with: music-analyzer playlist-recipe save --name NAME --file playlist-recipe.json', urgent: false}});
  assert.deepEqual(presentPlaylistRecipeExportEvent({type: 'playlist-recipe-export-failed', message: 'Min BPM must be a number'}),
    {status: {text: 'Recipe export failed: Min BPM must be a number', urgent: true}});
});
