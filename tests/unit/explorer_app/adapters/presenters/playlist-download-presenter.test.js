// Issues #146 and #137: what the Download M3U controls and the arc editor show for each playlist event.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
  playlistControlsViewModel, presentPlaylistDownloadEvent, presentRejectedPlaylistInput,
} from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/presenters/playlist-download-presenter.js';
import {
  EMPTY_PLAYLIST_DRAFT, addDraftArc, editDraftArc, editPlaylistDraft,
} from '../../../../../music_explorer/frameworks/explorer/assets/app/domain/playlist-draft.js';

const NO_ARCS = {arcs: [], arcLengthPlaceholder: 'tracks', lengthDisabled: false};

test('the controls show the draft, its choices and which inputs apply', () => {
  const draft = editPlaylistDraft(EMPTY_PLAYLIST_DRAFT, {harmonicMixing: false});
  assert.deepEqual(playlistControlsViewModel({draft, downloadState: 'idle', moods: ['happy']}), {
    values: draft,
    minimumKeyStrengthDisabled: true,
    ...NO_ARCS,
    downloadDisabled: false,
    arcShapeChoices: [['steady', 'Steady energy'], ['rise', 'Rising energy'],
      ['fall', 'Falling energy'], ['peak', 'Energy peak'], ['dip', 'Energy dip']],
    arcLengthUnitChoices: [['tracks', 'Tracks'], ['minutes', 'Minutes']],
    moodChoices: [['', 'No mood hold'], ['happy', 'Hold mood: happy']],
  });
});

test('each arc row shows its values and which way it can move', () => {
  let draft = addDraftArc(addDraftArc(addDraftArc(editPlaylistDraft(EMPTY_PLAYLIST_DRAFT, {arcLengthUnit: 'minutes'}))));
  draft = editDraftArc(draft, 1, {shape: 'peak', length: '20', low: '0.2', high: '0.9'});
  const view = playlistControlsViewModel({draft, downloadState: 'idle', moods: []});
  assert.deepEqual(view.arcs, [
    {shape: 'rise', length: '', low: '', high: '', canMoveEarlier: false, canMoveLater: true},
    {shape: 'peak', length: '20', low: '0.2', high: '0.9', canMoveEarlier: true, canMoveLater: true},
    {shape: 'rise', length: '', low: '', high: '', canMoveEarlier: true, canMoveLater: false},
  ]);
  assert.equal(view.arcLengthPlaceholder, 'minutes');
});

test("once an arc has a length, the track count and duration don't apply", () => {
  const draft = editDraftArc(addDraftArc(EMPTY_PLAYLIST_DRAFT), 0, {length: '8'});
  assert.equal(playlistControlsViewModel({draft, downloadState: 'idle', moods: []}).lengthDisabled, true);
});

test('the download button stays disabled while a download is in flight', () => {
  const view = playlistControlsViewModel({draft: EMPTY_PLAYLIST_DRAFT, downloadState: 'downloading', moods: []});
  assert.equal(view.downloadDisabled, true);
});

test('an edited draft shows its arcs and enables only the inputs that apply', () => {
  assert.deepEqual(presentPlaylistDownloadEvent({type: 'playlist-draft-edited', draft: EMPTY_PLAYLIST_DRAFT}),
    {minimumKeyStrengthDisabled: false, ...NO_ARCS});
  const draft = editDraftArc(addDraftArc(EMPTY_PLAYLIST_DRAFT), 0, {shape: 'dip', length: '5'});
  assert.deepEqual(presentPlaylistDownloadEvent({type: 'playlist-draft-edited', draft}), {
    minimumKeyStrengthDisabled: false, lengthDisabled: true, arcLengthPlaceholder: 'tracks',
    arcs: [{shape: 'dip', length: '5', low: '', high: '', canMoveEarlier: false, canMoveLater: false}]});
});

test('download events update the button and the status', () => {
  assert.deepEqual(presentPlaylistDownloadEvent({type: 'playlist-download-started'}), {downloadDisabled: true});
  assert.deepEqual(presentPlaylistDownloadEvent({type: 'playlist-downloaded', filename: 'a.m3u', warning: ''}),
    {downloadDisabled: false, status: {text: 'M3U downloaded.', urgent: false}});
  assert.deepEqual(presentPlaylistDownloadEvent({type: 'playlist-downloaded', filename: 'a.m3u', warning: 'dead end'}),
    {downloadDisabled: false, status: {text: 'M3U downloaded. Warning: dead end', urgent: false}});
  assert.deepEqual(presentPlaylistDownloadEvent({type: 'playlist-download-failed', message: 'bpm bounds must be ordered'}),
    {downloadDisabled: false, status: {text: 'M3U download failed: bpm bounds must be ordered', urgent: true}});
});

test('a rejected control value is an urgent status', () => {
  assert.deepEqual(presentRejectedPlaylistInput('Min BPM must be a number'),
    {status: {text: 'Min BPM must be a number', urgent: true}});
});
