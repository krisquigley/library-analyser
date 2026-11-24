// Issue #234: the playlist generator's later accordion steps, where the preview and the finishing actions go.
import {test, beforeEach} from 'node:test';
import assert from 'node:assert/strict';
import {playlistGeneratorSteps} from '../../../../../music_explorer/frameworks/explorer/assets/app/frameworks/views/playlist-steps-view.js';
import {installFakeDocument} from '../fake-document.js';

beforeEach(() => { installFakeDocument([]); });

test('Preview and Save, export and download are open accordion steps with their titles', () => {
  const {preview, finish} = playlistGeneratorSteps();
  assert.deepEqual([preview, finish].map(step => [step.tagName, step.id, step.open, step.className, step.children[0].textContent]),
    [['DETAILS', 'playlist-step-preview', true, 'playlist-step', 'Preview'],
      ['DETAILS', 'playlist-step-finish', true, 'playlist-step', 'Save, export and download']]);
});
