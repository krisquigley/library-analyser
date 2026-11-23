// Issue #139: the Export recipe button and its status.
import {test, beforeEach} from 'node:test';
import assert from 'node:assert/strict';
import {playlistRecipeExportView} from '../../../../../music_explorer/frameworks/explorer/assets/app/frameworks/views/playlist-recipe-export-view.js';
import {descendants, fakeElement, installFakeDocument} from '../fake-document.js';

beforeEach(() => { installFakeDocument([]); });

test('the button reports a click, and the status follows each update', () => {
  const clicks = [];
  const view = playlistRecipeExportView({onExportRequested: () => clicks.push('export')});
  const panel = fakeElement('section');
  view.mount(panel);
  const byId = id => descendants(panel).find(node => node.id === id);
  const button = byId('export-playlist-recipe');
  assert.deepEqual([button.type, button.textContent, clicks], ['button', 'Export recipe', []]);
  button.onclick();
  assert.deepEqual(clicks, ['export']);
  view.show({status: {text: 'Recipe export failed: no', urgent: true}});
  const status = byId('playlist-recipe-export-status');
  assert.deepEqual([status.textContent, status.getAttribute('role'), status.getAttribute('aria-live')],
    ['Recipe export failed: no', 'alert', 'assertive']);
});

test('showing before mounting does nothing', () => {
  assert.doesNotThrow(() => playlistRecipeExportView({onExportRequested() {}}).show({status: {text: 'x', urgent: false}}));
});
