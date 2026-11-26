// Issue #278: the strip over the graph that lists the hand-built playlist, with remove, clear and Download M3U.
import {test, beforeEach} from 'node:test';
import assert from 'node:assert/strict';
import {handBuiltPlaylistView} from '../../../../../music_explorer/frameworks/explorer/assets/app/frameworks/views/hand-built-playlist-view.js';
import {byTag, descendants, installFakeDocument} from '../fake-document.js';

let roots;
beforeEach(() => { roots = installFakeDocument(['hand-built-playlist']); });

const VIEW_MODEL = {hidden: false, heading: 'Your playlist · 2 tracks', downloadDisabled: false, clearDisabled: false,
  rows: [{trackId: 'a', text: '1. Alpha — Synthetic', removeLabel: 'Remove Alpha — Synthetic from your playlist'},
    {trackId: 'b', text: '2. Track 2', removeLabel: 'Remove track 2 from your playlist'}],
  notice: {text: '', urgent: false}};

function watching() {
  const heard = [];
  const view = handBuiltPlaylistView({onRemoveRequested: trackId => heard.push(['remove', trackId]),
    onClearRequested: () => heard.push(['clear']), onDownloadRequested: () => heard.push(['download'])});
  return {view, heard, strip: roots['hand-built-playlist']};
}

const byId = (strip, id) => descendants(strip).find(node => node.id === id);

test('the strip shows its heading and each track in order, with a button to remove it', () => {
  const {view, heard, strip} = watching();
  view.show(VIEW_MODEL);
  assert.equal(strip.hidden, false);
  assert.equal(byId(strip, 'hand-built-playlist-heading').textContent, 'Your playlist · 2 tracks');
  const rows = byId(strip, 'hand-built-playlist-tracks').children;
  assert.deepEqual(rows.map(row => [row.tagName, row.children[0].textContent, row.children[1].getAttribute('aria-label')]), [
    ['LI', '1. Alpha — Synthetic', 'Remove Alpha — Synthetic from your playlist'],
    ['LI', '2. Track 2', 'Remove track 2 from your playlist']]);
  rows[1].children[1].onclick();
  assert.deepEqual(heard, [['remove', 'b']]);
});

test('clear and Download M3U ask for what they say, and are disabled with nothing to act on', () => {
  const {view, heard, strip} = watching();
  view.show(VIEW_MODEL);
  const clear = byId(strip, 'hand-built-playlist-clear'), download = byId(strip, 'hand-built-playlist-download');
  assert.deepEqual([clear.textContent, download.textContent, clear.disabled, download.disabled], ['Clear', 'Download M3U', false, false]);
  clear.onclick(); download.onclick();
  assert.deepEqual(heard, [['clear'], ['download']]);
  view.show({...VIEW_MODEL, hidden: true, rows: [], downloadDisabled: true, clearDisabled: true});
  assert.deepEqual([strip.hidden, clear.disabled, download.disabled, byId(strip, 'hand-built-playlist-tracks').children],
    [true, true, true, []]);
  assert.equal(byTag(strip, 'button').length, 2, 'the buttons are kept, not rebuilt');
});

test('a notice or the download status is announced, urgently when something went wrong', () => {
  const {view, strip} = watching();
  view.show({...VIEW_MODEL, notice: {text: 'The playlist kept in this browser could not be read', urgent: true}});
  const status = byId(strip, 'hand-built-playlist-status');
  assert.deepEqual([status.textContent, status.getAttribute('role'), status.getAttribute('aria-live')],
    ['The playlist kept in this browser could not be read', 'alert', 'assertive']);
  view.showDownload({text: 'Preparing the M3U…', urgent: false});
  assert.deepEqual([status.textContent, status.getAttribute('role'), status.getAttribute('aria-live')],
    ['Preparing the M3U…', 'status', 'polite']);
});

test('a page without the strip shows nothing and does not fail', () => {
  installFakeDocument([]);
  const {view} = watching();
  view.show(VIEW_MODEL);
  view.showDownload({text: 'M3U downloaded', urgent: false});
});
