// Issues #146 and #137: what the Download M3U controls and the arc editor show for each playlist event.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
  libraryArousalRangeViewModel, playlistControlsViewModel, presentLoadedPlaylistDraft, presentPlaylistDownloadEvent, presentRejectedPlaylistInput,
} from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/presenters/playlist-download-presenter.js';
import {
  EMPTY_PLAYLIST_DRAFT, addDraftArc, editDraftArc, editPlaylistDraft,
} from '../../../../../music_explorer/frameworks/explorer/assets/app/domain/playlist-draft.js';

const NO_ARCS = {arcs: [], arcLengthUnit: 'tracks', lengthDisabled: false};

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
    arousalRange: 'Library arousal: not known until the graph has placed tracks with arousal.',
  });
  assert.equal(playlistControlsViewModel({draft, downloadState: 'idle', moods: [], arousalRange: {low: 3.12, high: 6.84}}).arousalRange,
    libraryArousalRangeViewModel({low: 3.12, high: 6.84}).arousalRange);
});

test("the arc editor names the library's arousal range, in the graph's numbers (#265)", () => {
  assert.deepEqual(libraryArousalRangeViewModel({low: 3.12, high: 6.84}), {arousalRange:
    "Library arousal: 3.1 to 6.8 (the graph's vertical axis). A blank low or high follows the tracks in your BPM range."});
  assert.deepEqual(libraryArousalRangeViewModel(null), {arousalRange: 'Library arousal: not known until the graph has placed tracks with arousal.'});
});

test('each arc row shows its values and which way it can move', () => {
  let draft = addDraftArc(addDraftArc(addDraftArc(editPlaylistDraft(EMPTY_PLAYLIST_DRAFT, {arcLengthUnit: 'minutes'}))));
  draft = editDraftArc(draft, 1, {shape: 'peak', length: '20', low: '0.2', high: '0.9'});
  const view = playlistControlsViewModel({draft, downloadState: 'idle', moods: []});
  assert.deepEqual(view.arcs, [
    {shape: 'rise', length: '', low: '', high: '', canMoveEarlier: false, canMoveLater: true,
      summary: 'Arc 1 · Rising energy · length not set · default energy range'},
    {shape: 'peak', length: '20', low: '0.2', high: '0.9', canMoveEarlier: true, canMoveLater: true,
      summary: 'Arc 2 · Energy peak · 20 minutes · energy 0.2 to 0.9'},
    {shape: 'rise', length: '', low: '', high: '', canMoveEarlier: true, canMoveLater: false,
      summary: 'Arc 3 · Rising energy · length not set · default energy range'},
  ]);
  assert.equal(view.arcLengthUnit, 'minutes');
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
    minimumKeyStrengthDisabled: false, lengthDisabled: true, arcLengthUnit: 'tracks',
    arcs: [{shape: 'dip', length: '5', low: '', high: '', canMoveEarlier: false, canMoveLater: false,
      summary: 'Arc 1 · Energy dip · 5 tracks · default energy range'}]});
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

test('a loaded draft shows its values in the controls, with its arcs and what they disable (#139)', () => {
  const loaded = editDraftArc(addDraftArc(editPlaylistDraft(EMPTY_PLAYLIST_DRAFT, {bpmMin: '118', harmonicMixing: false})), 0,
    {length: '6'});
  const view = presentLoadedPlaylistDraft(loaded);
  assert.equal(view.values, loaded);
  assert.deepEqual([view.minimumKeyStrengthDisabled, view.lengthDisabled, view.arcs.length], [true, true, 1]);
});

test('#234: a collapsed arc row sums itself up in one line, a half-set range included', () => {
  let draft = addDraftArc(addDraftArc(EMPTY_PLAYLIST_DRAFT));
  draft = editDraftArc(draft, 0, {length: '1', low: '0.3'});
  draft = editDraftArc(draft, 1, {shape: 'steady', high: '0.6'});
  assert.deepEqual(playlistControlsViewModel({draft, downloadState: 'idle', moods: []}).arcs.map(arc => arc.summary),
    ['Arc 1 · Rising energy · 1 track · energy from 0.3', 'Arc 2 · Steady energy · length not set · energy up to 0.6']);
});
