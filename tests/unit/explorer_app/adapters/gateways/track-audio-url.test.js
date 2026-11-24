// Issue #258: where the page asks for a track's audio.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {trackAudioUrl} from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/gateways/track-audio-url.js';

test("a track's audio is asked for by its ID, escaped", () => {
  assert.equal(trackAudioUrl('sha256:a b&c'), '/api/track-audio?track=sha256%3Aa%20b%26c');
});
