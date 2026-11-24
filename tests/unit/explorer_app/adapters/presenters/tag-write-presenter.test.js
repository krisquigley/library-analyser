// Issue #132: what the Write tags panel shows at each step of a previewed and approved tag write.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {presentRejectedTagWriteInput, presentTagWriteEvent, tagWriteViewModel} from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/presenters/tag-write-presenter.js';

test('the panel starts by inviting a preview, with nothing to write and no playlist to tag yet', () => {
  assert.deepEqual(tagWriteViewModel(), {busy: false, rows: [], skipped: [], report: [], canApply: false,
    playlistTarget: {available: false, label: 'Previewed playlist (preview one first)'},
    status: {text: 'Choose the selected track or the previewed playlist, then preview its BPM and key tags.', urgent: false}});
});

test('a previewed playlist becomes a target to tag, and stops being one when it is cleared', () => {
  assert.deepEqual(presentTagWriteEvent({type: 'tag-write-playlist-offered', count: 12}),
    {playlistTarget: {available: true, label: 'Previewed playlist (12 tracks)'}});
  assert.deepEqual(presentTagWriteEvent({type: 'tag-write-playlist-offered', count: 1}).playlistTarget.label,
    'Previewed playlist (1 track)');
  assert.deepEqual(presentTagWriteEvent({type: 'tag-write-playlist-withdrawn'}),
    {playlistTarget: {available: false, label: 'Previewed playlist (preview one first)'}});
});

test('a preview lists each change, old to new, and marks replacements', () => {
  const view = presentTagWriteEvent({type: 'tag-write-previewed', approvable: true, skipped: [], changes: [
    {file: 'one.mp3', field: 'bpm', current: null, proposed: '124', replaces: false},
    {file: 'one.mp3', field: 'key', current: 'C', proposed: 'Am', replaces: true}]});
  assert.deepEqual(view.rows, [{file: 'one.mp3', field: 'BPM', change: '(empty) → 124', replaces: false},
    {file: 'one.mp3', field: 'Key', change: 'C → Am (replaces)', replaces: true}]);
  assert.equal(view.canApply, true);
  assert.deepEqual(view.status, {text: '2 tag changes to write. Check them, then choose Write these tags.', urgent: false});
});

test('a preview with nothing to write says why for each track and cannot be applied', () => {
  const view = presentTagWriteEvent({type: 'tag-write-previewed', approvable: false, changes: [],
    skipped: [{trackId: 'sha256:a', reason: 'Nothing to change'}]});
  assert.deepEqual([view.rows, view.skipped, view.canApply], [[], ['Nothing to change'], false]);
  assert.deepEqual(view.status, {text: 'Nothing to write.', urgent: false});
});

test('busy steps disable the panel and an applied write reports every file and the rescan notice', () => {
  assert.deepEqual(presentTagWriteEvent({type: 'tag-write-previewing', trackIds: ['a']}),
    {busy: true, rows: [], skipped: [], report: [], canApply: false, status: {text: 'Reading the file’s tags…', urgent: false}});
  assert.deepEqual(presentTagWriteEvent({type: 'tag-write-applying'}),
    {busy: true, canApply: false, status: {text: 'Writing tags…', urgent: false}});
  const applied = presentTagWriteEvent({type: 'tag-write-applied', notice: 'Rescan them.', outcomes: [
    {file: 'one.mp3', status: 'written', detail: 'BPM 124'}, {file: 'two.flac', status: 'failed', detail: 'disk full'}]});
  assert.deepEqual(applied, {busy: false, canApply: false, rows: [], report: ['one.mp3: written (BPM 124)', 'two.flac: failed (disk full)'],
    status: {text: '1 written, 0 skipped, 1 failed. Rescan them.', urgent: true}});
});

test('a failure or a rejected request is told urgently and nothing can be written', () => {
  assert.deepEqual(presentTagWriteEvent({type: 'tag-write-failed', message: 'preview again'}),
    {busy: false, canApply: false, status: {text: 'Tags not written: preview again', urgent: true}});
  assert.deepEqual(presentRejectedTagWriteInput('Select a track first'),
    {status: {text: 'Select a track first', urgent: true}});
});

test('a discarded preview returns the panel to its start but keeps the playlist target as it is', () => {
  const {playlistTarget, ...start} = tagWriteViewModel();
  assert.deepEqual(presentTagWriteEvent({type: 'tag-write-discarded'}), start);
});
