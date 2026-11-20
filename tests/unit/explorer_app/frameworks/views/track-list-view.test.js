// Issue #146: the track list renders its view model as text and reports the listener's choices.
import {test, beforeEach} from 'node:test';
import assert from 'node:assert/strict';
import {trackListView} from '../../../../../music_explorer/frameworks/explorer/assets/app/frameworks/views/track-list-view.js';
import {byTag, descendants, installFakeDocument} from '../fake-document.js';

let roots;
beforeEach(() => { roots = installFakeDocument(['tracks', 'track-search']); });

const view = (changes = {}) => ({caption: 'Showing 2 of 9', status: '', busy: false, loadMore: null, retry: false,
  emptyMessage: '', emptyHidden: true,
  rows: [{trackId: 't1', title: 'One', artist: 'A', current: false}, {trackId: 't2', title: 'Two', artist: 'B', current: true}],
  ...changes});

function listening() {
  const heard = {chosen: [], typed: [], more: 0, retry: 0};
  const list = trackListView({onTrackChosen: id => heard.chosen.push(id), onQueryTyped: query => heard.typed.push(query),
    onLoadMore: () => { heard.more++; }, onRetry: () => { heard.retry++; }});
  return {list, heard};
}

test('the results are a title and artist table, one row per track, and a click chooses that track', () => {
  const {list, heard} = listening();
  list.show(view());
  assert.deepEqual(byTag(roots.tracks, 'th').map(cell => cell.textContent), ['Title', 'Artist']);
  const rows = byTag(byTag(roots.tracks, 'tbody')[0], 'tr');
  assert.deepEqual(rows.map(row => row.dataset.trackId), ['t1', 't2']);
  byTag(rows[0], 'button')[0].onclick();
  assert.deepEqual(heard.chosen, ['t1']);
});

test('the current track stays marked', () => {
  const {list} = listening();
  list.show(view());
  const [first, second] = byTag(byTag(roots.tracks, 'tbody')[0], 'tr');
  assert.deepEqual([first.className, second.className], ['', 'current']);
  assert.equal(byTag(second, 'button')[0].getAttribute('aria-current'), 'true');
});

test('hostile titles are shown as text, never as markup', () => {
  const {list} = listening();
  list.show(view({rows: [{trackId: 'x', title: '<img src=x onerror=alert(1)>', artist: '<b>A</b>', current: false}]}));
  assert.equal(byTag(roots.tracks, 'button')[0].textContent, '<img src=x onerror=alert(1)>');
  assert.ok(!descendants(roots.tracks).some(node => node.tagName === 'IMG' || node.tagName === 'B'));
});

test('Load more and Retry search report the listener\'s click', () => {
  const {list, heard} = listening();
  list.show(view({loadMore: {disabled: false}, retry: true}));
  const buttons = byTag(roots.tracks, 'button').filter(button => !['One', 'Two'].includes(button.textContent));
  assert.deepEqual(buttons.map(button => button.textContent), ['Load more tracks', 'Retry search']);
  buttons.forEach(button => button.onclick());
  assert.deepEqual([heard.more, heard.retry], [1, 1]);
});

test('the status is announced politely, and the list is busy while searching', () => {
  const {list} = listening();
  list.show(view({status: 'Searching…', busy: true}));
  const status = descendants(roots.tracks).find(node => node.textContent === 'Searching…');
  assert.deepEqual([status.getAttribute('role'), status.getAttribute('aria-live')], ['status', 'polite']);
  assert.equal(roots.tracks.getAttribute('aria-busy'), 'true');
});

test('the search box reports what is typed, and is wired only once', () => {
  const {list, heard} = listening();
  list.show(view());
  const handler = roots['track-search'].oninput;
  list.show(view());
  assert.equal(roots['track-search'].oninput, handler);
  roots['track-search'].value = 'alp';
  handler();
  assert.deepEqual(heard.typed, ['alp']);
});
