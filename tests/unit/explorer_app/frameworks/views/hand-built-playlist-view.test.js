// Issue #278: the strip over the graph that lists the hand-built playlist, with remove, clear and Download M3U.
// Issue #287: it is a table like the playlist preview's, each track with ▶ to play it.
import {test, beforeEach} from 'node:test';
import assert from 'node:assert/strict';
import {handBuiltPlaylistView} from '../../../../../music_explorer/frameworks/explorer/assets/app/frameworks/views/hand-built-playlist-view.js';
import {byTag, descendants, installFakeDocument} from '../fake-document.js';

let roots;
beforeEach(() => { roots = installFakeDocument(['hand-built-playlist']); });

const row = (trackId, place, track, fields = {}) => ({trackId, place, track, length: '3:20', bpm: '120.0', key: 'C major',
  energy: '4.3', transition: place === '1' ? 'Start' : 'Key compatible, +4.0 BPM', playable: true,
  removeLabel: `Remove ${track} from your playlist`, ...fields});
const VIEW_MODEL = {hidden: false, heading: 'Your playlist · 2 tracks · 6:40', downloadDisabled: false, clearDisabled: false,
  rows: [row('a', '1', 'Synthetic – Alpha'),
    row('gone', '2', 'No longer playable from the library', {playable: false, removeLabel: 'Remove track 2 from your playlist'})],
  notice: {text: '', urgent: false}};
const idle = {text: '▶', verb: 'Play', pressed: false};

function watching() {
  const heard = [];
  const view = handBuiltPlaylistView({onRemoveRequested: trackId => heard.push(['remove', trackId]),
    onClearRequested: () => heard.push(['clear']), onDownloadRequested: () => heard.push(['download']),
    onPlayRequested: trackId => heard.push(['play', trackId])});
  return {view, heard, strip: roots['hand-built-playlist']};
}

const byId = (strip, id) => descendants(strip).find(node => node.id === id);
const cells = line => line.children.map(cell => cell.children.length ? cell.children[0] : cell);

test('the strip is a table of the tracks in order, like the playlist preview, each with play and remove', () => {
  const {view, heard, strip} = watching();
  view.show(VIEW_MODEL);
  assert.equal(strip.hidden, false);
  assert.equal(byId(strip, 'hand-built-playlist-heading').textContent, 'Your playlist · 2 tracks · 6:40');
  const table = byTag(strip, 'table')[0];
  assert.equal(table.className, 'playlist-preview-table hand-built-playlist-table');
  assert.deepEqual(byTag(table, 'th').map(heading => heading.textContent),
    ['Play', '#', 'Track', 'Length', 'BPM', 'Key', 'Energy', 'Transition', 'Remove']);
  const lines = byId(strip, 'hand-built-playlist-tracks').children;
  assert.deepEqual(lines.map(line => cells(line).slice(1, 8).map(cell => cell.textContent)), [
    ['1', 'Synthetic – Alpha', '3:20', '120.0', 'C major', '4.3', 'Start'],
    ['2', 'No longer playable from the library', '3:20', '120.0', 'C major', '4.3', 'Key compatible, +4.0 BPM']]);
  const [play, remove] = [cells(lines[0])[0], cells(lines[0])[8]];
  assert.deepEqual([play.textContent, play.getAttribute('aria-label'), play.disabled], ['▶', 'Play Synthetic – Alpha', false]);
  assert.equal(cells(lines[1])[0].disabled, true, 'a track no longer playable cannot be played');
  assert.equal(remove.getAttribute('aria-label'), 'Remove Synthetic – Alpha from your playlist');
  play.onclick(); cells(lines[1])[8].onclick();
  assert.deepEqual(heard, [['play', 'a'], ['remove', 'gone']]);
});

test("the playing track's button offers pause, and rows shown later match the playback", () => {
  const {view, strip} = watching();
  view.show(VIEW_MODEL);
  view.showPlayback({activeTrackId: 'a', activeButton: {text: '❚❚', verb: 'Pause', pressed: true}, idleButton: idle});
  const play = () => cells(byId(strip, 'hand-built-playlist-tracks').children[0])[0];
  assert.deepEqual([play().textContent, play().getAttribute('aria-label'), play().getAttribute('aria-pressed')],
    ['❚❚', 'Pause Synthetic – Alpha', 'true']);
  view.show(VIEW_MODEL);
  assert.equal(play().textContent, '❚❚');
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
  assert.deepEqual([byId(strip, 'hand-built-playlist-clear'), byId(strip, 'hand-built-playlist-download')], [clear, download],
    'the buttons are kept, not rebuilt');
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
  view.showPlayback({activeTrackId: null, activeButton: idle, idleButton: idle});
});
