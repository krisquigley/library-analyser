// Issue #139: listing the saved recipes and loading one into the draft. The Explorer only reads them.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createSavedRecipeLoad} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/load-saved-recipe/load-saved-recipe.js';
import {SAVED_RECIPE_EVENT_TYPES} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/load-saved-recipe/saved-recipe-events.js';
import {EMPTY_PLAYLIST_DRAFT} from '../../../../../music_explorer/frameworks/explorer/assets/app/domain/playlist-draft.js';
import {playlistRecipeDocument} from '../../../../../music_explorer/frameworks/explorer/assets/app/domain/playlist-recipe-document.js';

const LISTED = [{name: 'Warm-up', updatedAt: '2026-11-20T10:00:00Z', problem: null}];
const SAVED = playlistRecipeDocument({...EMPTY_PLAYLIST_DRAFT, bpmMin: '118', bpmMax: '126', count: '12'}, 'track-9');

function harness(api = {}) {
  let session = {draft: EMPTY_PLAYLIST_DRAFT};
  const published = [];
  const explorerApi = {listSavedPlaylistRecipes: async () => LISTED,
    loadSavedPlaylistRecipe: async name => ({name, recipe: SAVED}), ...api};
  const recipes = createSavedRecipeLoad({explorerApi,
    playlistDraft: {read: () => session, write(changes) { session = {...session, ...changes}; }},
    eventBus: {publish: event => published.push(event), subscribe() {}}});
  return {recipes, published, draft: () => session.draft};
}

test('the event types are the ones the use case publishes', () => {
  assert.deepEqual(SAVED_RECIPE_EVENT_TYPES, ['saved-recipes-listing', 'saved-recipes-listed', 'saved-recipe-loading',
    'saved-recipe-loaded', 'saved-recipe-failed']);
});

test('listing publishes the saved recipes', async () => {
  const {recipes, published} = harness();
  await recipes.list();
  assert.deepEqual(published, [{type: 'saved-recipes-listing'}, {type: 'saved-recipes-listed', recipes: LISTED}]);
  assert.equal(recipes.state(), 'listed');
});

test('loading a recipe replaces the draft and names its start track', async () => {
  const {recipes, published, draft} = harness();
  await recipes.list();
  await recipes.load('Warm-up');
  assert.deepEqual([draft().bpmMin, draft().bpmMax, draft().count], ['118', '126', '12']);
  assert.deepEqual(published.slice(2), [{type: 'saved-recipe-loading', name: 'Warm-up'},
    {type: 'saved-recipe-loaded', name: 'Warm-up', startTrackId: 'track-9', draft: draft()}]);
  assert.equal(recipes.state(), 'loaded');
});

test('a list or recipe that cannot be read is told, and the draft is kept', async () => {
  const refused = harness({listSavedPlaylistRecipes: async () => { throw new Error('database is locked'); }});
  await refused.recipes.list();
  assert.deepEqual(refused.published.at(-1), {type: 'saved-recipe-failed', message: 'database is locked'});
  const unreadable = harness({loadSavedPlaylistRecipe: async name => ({name, recipe: {...SAVED, version: 7}})});
  await unreadable.recipes.list();
  await unreadable.recipes.load('Warm-up');
  assert.deepEqual(unreadable.published.at(-1),
    {type: 'saved-recipe-failed', message: 'Recipe version 7 is not supported; only version 1 can be read'});
  assert.equal(unreadable.draft(), EMPTY_PLAYLIST_DRAFT);
});

test('a load while another is in flight is refused as a domain error', async () => {
  let answer;
  const {recipes} = harness({loadSavedPlaylistRecipe: () => new Promise(resolve => { answer = resolve; })});
  await recipes.list();
  const first = recipes.load('Warm-up');
  await assert.rejects(recipes.load('Warm-up'), /cannot load while loading/);
  answer({name: 'Warm-up', recipe: SAVED});
  await first;
  assert.equal(recipes.state(), 'loaded');
});
