// Issue #243: a selected track and its nearest neighbours stay in focus; the rest of the graph is dimmed.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {isFocusedLink, isFocusedTrack, neighbourFocus} from '../../../../music_explorer/frameworks/explorer/assets/app/domain/neighbour-focus.js';

const GRAPH = {trackIds: ['a', 'b', 'c', 'd'], links: [{source: 'a', target: 'b'}, {source: 'c', target: 'a'}, {source: 'c', target: 'd'}]};

test('without a selection, or with one the graph does not show, everything is in focus', () => {
  for (const selected of [null, '', 'hidden']) {
    const focus = neighbourFocus(GRAPH, selected);
    assert.equal(focus.active, false);
    assert.equal(isFocusedTrack(focus, 'd'), true);
    assert.equal(isFocusedLink(focus, {source: 'c', target: 'd'}), true);
  }
});

test('the selected track and the tracks linked to it in either direction are in focus, and only their links to it', () => {
  const focus = neighbourFocus(GRAPH, 'a');
  assert.equal(focus.active, true);
  assert.deepEqual(['a', 'b', 'c', 'd'].map(id => isFocusedTrack(focus, id)), [true, true, true, false]);
  assert.deepEqual(GRAPH.links.map(link => isFocusedLink(focus, link)), [true, true, false]);
  assert.deepEqual([...focus.neighbourIds], ['b', 'c']);
});

test('a track with no links is in focus alone', () => {
  const focus = neighbourFocus(GRAPH, 'd') ;
  assert.deepEqual([...focus.neighbourIds], ['c']);
  const lonely = neighbourFocus({trackIds: ['a', 'e'], links: [{source: 'a', target: 'b'}]}, 'e');
  assert.deepEqual([lonely.active, [...lonely.neighbourIds], isFocusedTrack(lonely, 'a')], [true, [], false]);
});

test('only links between visible tracks count, so a filtered-out neighbour is not in focus', () => {
  const focus = neighbourFocus({trackIds: ['a', 'c'], links: GRAPH.links}, 'a');
  assert.deepEqual([...focus.neighbourIds], ['c']);
});
