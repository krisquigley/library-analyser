// Issue #139: exporting the drafted playlist as a recipe file; the analyzer saves it, never the Explorer.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createPlaylistRecipeExport} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/export-playlist-recipe/export-playlist-recipe.js';
import {PLAYLIST_RECIPE_EXPORT_EVENT_TYPES} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/export-playlist-recipe/playlist-recipe-export-events.js';
import {EMPTY_PLAYLIST_DRAFT} from '../../../../../music_explorer/frameworks/explorer/assets/app/domain/playlist-draft.js';

function harness({draft = {...EMPTY_PLAYLIST_DRAFT, bpmMin: '120', bpmMax: '128'}, save} = {}) {
  const saved = [];
  const published = [];
  const recipeExport = createPlaylistRecipeExport({playlistDraft: {read: () => ({draft}), write() {}},
    playlistFile: {save: save || (file => saved.push(file))}, eventBus: {publish: event => published.push(event), subscribe() {}}});
  return {recipeExport, saved, published};
}

test('the event types are the ones the use case publishes', () => {
  assert.deepEqual(PLAYLIST_RECIPE_EXPORT_EVENT_TYPES, ['playlist-recipe-exported', 'playlist-recipe-export-failed']);
});

test('the draft is offered as a JSON recipe file from the start track', () => {
  const {recipeExport, saved, published} = harness();
  recipeExport.exportRecipe('track-1');
  assert.equal(saved.length, 1);
  assert.deepEqual([saved[0].filename, saved[0].contentType], ['playlist-recipe.json', 'application/json']);
  const document = JSON.parse(saved[0].contents);
  assert.deepEqual([document.format, document.version, document.start_track_id, document.bpm], ['playlist-recipe', 2, 'track-1',
    {min: 120, max: 128}]);
  assert.ok(saved[0].contents.endsWith('}\n'));
  assert.deepEqual(published, [{type: 'playlist-recipe-exported', filename: 'playlist-recipe.json'}]);
});

test('a draft that cannot be a recipe, or a file that cannot be offered, is told and saves nothing', () => {
  const blank = harness({draft: EMPTY_PLAYLIST_DRAFT});
  blank.recipeExport.exportRecipe('track-1');
  assert.deepEqual([blank.saved, blank.published], [[], [{type: 'playlist-recipe-export-failed', message: 'Min BPM must be a number'}]]);
  const refused = harness({save: () => { throw new Error('downloads are blocked'); }});
  refused.recipeExport.exportRecipe('track-1');
  assert.deepEqual(refused.published, [{type: 'playlist-recipe-export-failed', message: 'downloads are blocked'}]);
});
