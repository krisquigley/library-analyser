// Issue #146: the mood tracker and the graph filters on screen, and the listener's input they report.
import {test, beforeEach} from 'node:test';
import assert from 'node:assert/strict';
import {graphControlsView} from '../../../../../music_explorer/frameworks/explorer/assets/app/frameworks/views/graph-controls-view.js';
import {descendants, fakeElement, installFakeDocument} from '../fake-document.js';

beforeEach(() => { installFakeDocument([]); });

function mounted() {
  const heard = {moods: [], bpm: [], genres: [], cleared: 0};
  const view = graphControlsView({onMoodChosen: mood => heard.moods.push(mood), onBpmRangeEdited: range => heard.bpm.push(range),
    onGenresEdited: genres => heard.genres.push(genres), onFiltersCleared: () => { heard.cleared++; }});
  const root = fakeElement('div');
  view.mount(root);
  const byId = (id, within = root) => descendants(within).find(node => node.id === id);
  return {view, heard, root, byId};
}

test('the mood tracker has its own group, apart from the graph filters', () => {
  const {byId} = mounted();
  const [moodGroup, filters] = [byId('mood-tracker-controls'), byId('graph-controls')];
  assert.equal(moodGroup.children[0].textContent, 'Selected mood strength');
  assert.equal(byId('selected-mood', moodGroup).tagName, 'SELECT');
  assert.equal(byId('selected-mood', filters), undefined);
  assert.equal(filters.children[0].textContent, 'Graph filters');
});

test('the BPM inputs are named for assistive technology, not only by their placeholders', () => {
  const {byId} = mounted();
  assert.deepEqual(['bpm-min', 'bpm-max'].map(id => [byId(id).type, byId(id).getAttribute('aria-label')]),
    [['number', 'Minimum BPM'], ['number', 'Maximum BPM']]);
});

test('the controls report the mood, the BPM range, the genres and a clear', () => {
  const {heard, byId} = mounted();
  byId('selected-mood').value = 'happy';
  byId('selected-mood').onchange();
  byId('bpm-min').value = '100';
  byId('bpm-min').onchange();
  byId('genre-filter').selectedOptions = [{value: 'rock'}, {value: 'jazz'}];
  byId('genre-filter').onchange();
  byId('clear-graph-filters').onclick();
  assert.deepEqual([heard.moods, heard.bpm, heard.genres, heard.cleared],
    [['happy'], [{bpmMin: '100', bpmMax: ''}], [['rock', 'jazz']], 1]);
});

test('the mood and genre choices render, and the chosen genres are shown selected', () => {
  const {view, byId} = mounted();
  view.showOptions({moodChoices: [{value: 'happy', label: 'happy', selected: true}],
    genreChoices: [{value: 'rock', label: 'rock', selected: false}, {value: 'jazz', label: 'jazz', selected: false}]});
  assert.deepEqual(byId('genre-filter').children.map(option => [option.value, option.textContent]), [['rock', 'rock'], ['jazz', 'jazz']]);
  assert.equal(byId('selected-mood').children[0].selected, true);
  view.showValues({bpmMin: '90', bpmMax: '', genres: ['jazz']});
  assert.deepEqual(byId('genre-filter').children.map(option => option.selected), [false, true]);
  assert.equal(byId('bpm-min').value, '90');
});

test('a rejected filter value is an alert in the filter status', () => {
  const {view, byId} = mounted();
  view.showRejection('Min BPM must be a number');
  const status = byId('graph-filter-status');
  assert.deepEqual([status.getAttribute('role'), status.textContent], ['alert', 'Min BPM must be a number']);
});
