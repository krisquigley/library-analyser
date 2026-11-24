// Issue #132: the Write tags panel on screen: choose a policy, preview, check the changes, then write them.
import {test, beforeEach} from 'node:test';
import assert from 'node:assert/strict';
import {tagWriteView} from '../../../../../music_explorer/frameworks/explorer/assets/app/frameworks/views/tag-write-view.js';
import {tagWriteViewModel} from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/presenters/tag-write-presenter.js';
import {descendants, fakeElement, installFakeDocument} from '../fake-document.js';

beforeEach(() => { installFakeDocument([]); });

function mounted() {
  const heard = [];
  const view = tagWriteView({onPreviewRequested: (policy, target) => heard.push(['preview', policy, target]), onApplyRequested: () => heard.push(['apply'])});
  const panel = fakeElement('section');
  view.mount(panel, tagWriteViewModel());
  const byId = id => descendants(panel).find(node => node.id === id);
  return {view, heard, byId};
}

test('Preview tags reports the chosen policy; Write these tags is disabled until a preview can be applied', () => {
  const {heard, byId} = mounted();
  assert.deepEqual(byId('tag-write-policy').children.map(option => option.value), ['fill-empty', 'replace-existing']);
  assert.equal(byId('tag-write-apply').disabled, true);
  byId('tag-write-policy').value = 'replace-existing';
  byId('tag-write-target').value = 'selected-track';
  byId('tag-write-preview').onclick();
  assert.deepEqual(heard, [['preview', 'replace-existing', 'selected-track']]);
  assert.equal(byId('tag-write-status').textContent, 'Choose the selected track or the previewed playlist, then preview its BPM and key tags.');
});

test('a preview shows each change, and Write these tags asks to apply it', () => {
  const {view, heard, byId} = mounted();
  view.show({busy: false, canApply: true, report: [], skipped: ['Nothing to change'],
    rows: [{file: 'one.mp3', field: 'BPM', change: '(empty) → 124', replaces: false}],
    status: {text: '1 tag change to write.', urgent: false}});
  const rows = byId('tag-write-changes').children;
  assert.deepEqual(rows.map(row => row.children.map(cell => cell.textContent)), [['one.mp3', 'BPM', '(empty) → 124']]);
  assert.deepEqual(byId('tag-write-skipped').children.map(item => item.textContent), ['Nothing to change']);
  assert.equal(byId('tag-write-apply').disabled, false);
  byId('tag-write-apply').onclick();
  assert.deepEqual(heard, [['apply']]);
});

test('busy disables both buttons, and the per-file report and a failure are shown', () => {
  const {view, byId} = mounted();
  view.show({busy: true, canApply: false, status: {text: 'Writing tags…', urgent: false}});
  assert.deepEqual([byId('tag-write-preview').disabled, byId('tag-write-apply').disabled], [true, true]);
  view.show({busy: false, canApply: false, rows: [], report: ['one.mp3: written (BPM 124)'],
    status: {text: '1 written, 0 skipped, 0 failed. Rescan them.', urgent: false}});
  assert.deepEqual(byId('tag-write-report').children.map(item => item.textContent), ['one.mp3: written (BPM 124)']);
  assert.equal(byId('tag-write-changes').children.length, 0);
  view.show({busy: false, canApply: false, status: {text: 'Tags not written: preview again', urgent: true}});
  assert.equal(byId('tag-write-status').getAttribute('role'), 'alert');
});

test('showing before mounting does nothing', () => {
  assert.doesNotThrow(() => tagWriteView({onPreviewRequested() {}, onApplyRequested() {}}).show({busy: true}));
});

test('the previewed playlist is a target only once one is offered, and its label counts its tracks', () => {
  const {view, byId} = mounted();
  const target = byId('tag-write-target');
  assert.deepEqual(target.children.map(option => [option.value, option.disabled]),
    [['selected-track', false], ['previewed-playlist', true]]);
  assert.equal(target.children[1].textContent, 'Previewed playlist (preview one first)');
  view.show({playlistTarget: {available: true, label: 'Previewed playlist (12 tracks)'}});
  assert.deepEqual([target.children[1].disabled, target.children[1].textContent], [false, 'Previewed playlist (12 tracks)']);
  target.value = 'previewed-playlist';
  view.show({playlistTarget: {available: false, label: 'Previewed playlist (preview one first)'}});
  assert.equal(target.value, 'selected-track', 'a withdrawn playlist is no longer chosen');
});
