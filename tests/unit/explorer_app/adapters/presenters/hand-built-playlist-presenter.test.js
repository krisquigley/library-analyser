// Issue #278: what the strip over the graph shows of the hand-built playlist and its download.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
  handBuiltPlaylistViewModel, presentHandBuiltPlaylistDownload,
} from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/presenters/hand-built-playlist-presenter.js';

const labelled = (trackId, title) => ({trackId, title, artist: 'Synthetic'});

test('the strip lists the tracks in order, each named and removable, with a count', () => {
  const long = 'A very long synthetic title that goes on and on';
  assert.deepEqual(handBuiltPlaylistViewModel({trackIds: ['a', 'b', 'c'], labels: [labelled('a', 'Alpha'), labelled('c', long)],
    notice: ''}), {
    hidden: false, heading: 'Your playlist · 3 tracks', downloadDisabled: false, clearDisabled: false,
    rows: [
      {trackId: 'a', text: '1. Alpha — Synthetic', removeLabel: 'Remove Alpha — Synthetic from your playlist'},
      {trackId: 'b', text: '2. Track 2', removeLabel: 'Remove track 2 from your playlist'},
      {trackId: 'c', text: '3. A very long synthetic title th… — Synthetic',
        removeLabel: 'Remove A very long synthetic title th… — Synthetic from your playlist'}],
    notice: {text: '', urgent: false}});
});

test('one track is counted as one, and an empty playlist hides the strip unless there is something to say', () => {
  assert.equal(handBuiltPlaylistViewModel({trackIds: ['a'], labels: [], notice: ''}).heading, 'Your playlist · 1 track');
  const empty = handBuiltPlaylistViewModel({trackIds: [], labels: [], notice: ''});
  assert.deepEqual([empty.hidden, empty.downloadDisabled, empty.clearDisabled, empty.rows], [true, true, true, []]);
  const told = handBuiltPlaylistViewModel({trackIds: [], labels: [], notice: 'The playlist kept in this browser could not be read'});
  assert.deepEqual([told.hidden, told.notice], [false, {text: 'The playlist kept in this browser could not be read', urgent: true}]);
});

test('the download says what it is doing, and why it failed', () => {
  assert.deepEqual(['hand-built-playlist-download-started', 'hand-built-playlist-downloaded'].map(type => presentHandBuiltPlaylistDownload({type})), [
    {text: 'Preparing the M3U…', urgent: false}, {text: 'M3U downloaded', urgent: false}]);
  assert.deepEqual(presentHandBuiltPlaylistDownload({type: 'hand-built-playlist-download-failed', message: 'Track 2 is gone'}),
    {text: 'Could not download the playlist: Track 2 is gone', urgent: true});
});
