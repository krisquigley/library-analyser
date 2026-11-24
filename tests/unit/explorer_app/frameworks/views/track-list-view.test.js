// Issue #146: the track list renders its view model as text and reports the listener's choices.
import {test, beforeEach} from 'node:test';
import assert from 'node:assert/strict';
import {trackListView} from '../../../../../music_explorer/frameworks/explorer/assets/app/frameworks/views/track-list-view.js';
import {byTag, descendants, installFakeDocument} from '../fake-document.js';

let roots;
beforeEach(() => { roots = installFakeDocument(['tracks', 'track-search']); });

const view = (changes = {}) => ({caption: 'Showing 2 of 9', status: '', busy: false, loadMore: null, retry: false,
  emptyMessage: '', emptyHidden: true,
  tone: 'results',
  rows: [{trackId: 't1', title: 'One', artist: 'A', bpmBadge: '124 BPM', current: false},
    {trackId: 't2', title: 'Two', artist: 'B', bpmBadge: null, current: true}],
  ...changes});

function listening() {
  const heard = {chosen: [], typed: [], more: 0, retry: 0};
  const list = trackListView({onTrackChosen: id => heard.chosen.push(id), onQueryTyped: query => heard.typed.push(query),
    onLoadMore: () => { heard.more++; }, onRetry: () => { heard.retry++; }});
  return {list, heard};
}

test('each result is a row with the title over the artist and its BPM badge, and a click chooses that track (#235)', () => {
  const {list, heard} = listening();
  list.show(view());
  assert.deepEqual(byTag(roots.tracks, 'th').map(cell => cell.textContent), ['Title', 'Artist']);
  assert.equal(byTag(roots.tracks, 'thead')[0].className, 'visually-hidden', 'headings are for screen readers');
  const rows = byTag(byTag(roots.tracks, 'tbody')[0], 'tr');
  assert.deepEqual(rows.map(row => row.dataset.trackId), ['t1', 't2']);
  assert.deepEqual(rows.map(row => byTag(row, 'td').map(cell => cell.className)), [['track-title', 'track-artist'], ['track-title', 'track-artist']]);
  assert.equal(byTag(rows[0], 'button')[0].textContent, 'One', 'the button is named by the title alone');
  assert.deepEqual(byTag(rows[0], 'span').map(badge => [badge.className, badge.textContent]), [['track-badge', '124 BPM']]);
  assert.deepEqual(byTag(rows[1], 'span'), [], 'no badge when the BPM is unknown');
  byTag(rows[0], 'button')[0].onclick();
  assert.deepEqual(heard.chosen, ['t1']);
});

test('the up and down arrow keys move from row to row (#235)', () => {
  const {list} = listening();
  list.show(view({rows: [1, 2, 3].map(n => ({trackId: 't' + n, title: 'T' + n, artist: 'A', bpmBadge: null, current: false}))}));
  const body = byTag(roots.tracks, 'tbody')[0];
  const buttons = byTag(body, 'button');
  const press = (key, from) => { const event = {key, target: from, prevented: false, preventDefault() { this.prevented = true; }}; body.onkeydown(event); return event; };
  buttons.forEach(button => { button.focused = false; });
  assert.equal(press('ArrowDown', buttons[0]).prevented, true);
  assert.equal(buttons[1].focused, true);
  press('ArrowUp', buttons[1]);
  assert.equal(buttons[0].focused, true);
  buttons[0].focused = false;
  press('ArrowUp', buttons[0]);
  assert.equal(buttons[0].focused, false, 'the first row stays put');
  press('ArrowDown', buttons[2]);
  assert.equal(press('Enter', buttons[2]).prevented, false, 'other keys keep their meaning');
});

test('a failed search is an alert, and other states are announced politely, each with its tone (#235)', () => {
  const {list} = listening();
  list.show(view({tone: 'failed', status: 'Search failed: offline', retry: true}));
  const status = descendants(roots.tracks).find(node => node.textContent === 'Search failed: offline');
  assert.deepEqual([status.getAttribute('role'), status.className], ['alert', 'track-list-status failed']);
  assert.equal(roots.tracks.dataset.tone, 'failed');
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

test('badges are set on the rows already shown, without replacing them (#235)', () => {
  const {list} = listening();
  list.show(view());
  const rows = byTag(byTag(roots.tracks, 'tbody')[0], 'tr');
  list.showBpmBadges([{trackId: 't1', bpmBadge: null}, {trackId: 't2', bpmBadge: '98 BPM'}]);
  const after = byTag(byTag(roots.tracks, 'tbody')[0], 'tr');
  assert.deepEqual(after, rows, 'the same rows');
  assert.deepEqual(after.map(row => byTag(row, 'span').map(badge => badge.textContent)), [[], ['98 BPM']]);
  assert.equal(byTag(after[1], 'td')[1].textContent, 'B', 'the artist stays');
});
