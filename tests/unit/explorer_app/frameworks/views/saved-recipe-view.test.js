// Issue #139: the saved recipe controls on screen.
import {test, beforeEach} from 'node:test';
import assert from 'node:assert/strict';
import {savedRecipeView} from '../../../../../music_explorer/frameworks/explorer/assets/app/frameworks/views/saved-recipe-view.js';
import {descendants, fakeElement, installFakeDocument} from '../fake-document.js';

beforeEach(() => { installFakeDocument([]); });

function mounted() {
  const heard = [];
  const view = savedRecipeView({onListRequested: () => heard.push(['list']), onLoadRequested: name => heard.push(['load', name])});
  const panel = fakeElement('section');
  view.mount(panel, {busy: false, choices: null, status: {text: '', urgent: false}});
  const byId = id => descendants(panel).find(node => node.id === id);
  return {view, heard, byId};
}

test('Saved recipes asks for the list; Load is hidden until there are choices', () => {
  const {heard, byId} = mounted();
  assert.equal(byId('saved-recipes-list').textContent, 'Saved recipes');
  assert.deepEqual([byId('saved-recipe-choice').hidden, byId('saved-recipe-load').hidden], [true, true]);
  byId('saved-recipes-list').onclick();
  assert.deepEqual(heard, [['list']]);
});

test('choices fill the picker, and Load reports the chosen name', () => {
  const {view, heard, byId} = mounted();
  view.show({busy: false, status: {text: '2 saved recipes.', urgent: false}, choices: [
    {value: 'Warm-up', label: 'Warm-up (saved 2026-11-20)', disabled: false, title: ''},
    {value: 'Old', label: 'Old (cannot load)', disabled: true, title: 'gone'}]});
  const choice = byId('saved-recipe-choice');
  assert.equal(choice.hidden, false);
  assert.deepEqual(choice.children.map(option => [option.value, option.textContent, option.disabled, option.title]),
    [['Warm-up', 'Warm-up (saved 2026-11-20)', false, ''], ['Old', 'Old (cannot load)', true, 'gone']]);
  choice.value = 'Warm-up';
  byId('saved-recipe-load').onclick();
  assert.deepEqual(heard, [['load', 'Warm-up']]);
});

test('busy disables the buttons, and a failure is an alert', () => {
  const {view, byId} = mounted();
  view.show({busy: true, status: {text: 'Reading saved recipes…', urgent: false}});
  assert.deepEqual([byId('saved-recipes-list').disabled, byId('saved-recipe-load').disabled], [true, true]);
  view.show({busy: false, status: {text: 'Saved recipe failed: no', urgent: true}});
  const status = byId('saved-recipe-status');
  assert.deepEqual([status.textContent, status.getAttribute('role'), byId('saved-recipes-list').disabled], ['Saved recipe failed: no', 'alert', false]);
});

test('showing before mounting does nothing', () => {
  assert.doesNotThrow(() => savedRecipeView({onListRequested() {}, onLoadRequested() {}}).show({busy: true}));
});
