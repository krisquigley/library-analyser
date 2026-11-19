// Issue #146: what the Download M3U controls show for each playlist download event.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
  playlistControlsViewModel, presentPlaylistDownloadEvent, presentRejectedPlaylistInput,
} from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/presenters/playlist-download-presenter.js';
import {EMPTY_PLAYLIST_DRAFT, editPlaylistDraft} from '../../../../../music_explorer/frameworks/explorer/assets/app/domain/playlist-draft.js';

test('the controls show the draft, its choices and which inputs apply', () => {
  const draft = editPlaylistDraft(EMPTY_PLAYLIST_DRAFT, {harmonicMixing: false, energyArc: 'rise'});
  assert.deepEqual(playlistControlsViewModel({draft, downloadState: 'idle', moods: ['happy']}), {
    values: draft,
    minimumKeyStrengthDisabled: true,
    energyRangeDisabled: false,
    downloadDisabled: false,
    arcChoices: [['none', 'No energy arc'], ['steady', 'Steady energy'], ['rise', 'Rising energy'],
      ['fall', 'Falling energy'], ['peak', 'Energy peak']],
    moodChoices: [['', 'No mood hold'], ['happy', 'Hold mood: happy']],
  });
});

test('the download button stays disabled while a download is in flight', () => {
  const view = playlistControlsViewModel({draft: EMPTY_PLAYLIST_DRAFT, downloadState: 'downloading', moods: []});
  assert.equal(view.downloadDisabled, true);
});

test('an edited draft enables only the inputs that apply', () => {
  assert.deepEqual(presentPlaylistDownloadEvent({type: 'playlist-draft-edited', draft: EMPTY_PLAYLIST_DRAFT}),
    {minimumKeyStrengthDisabled: false, energyRangeDisabled: true});
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
