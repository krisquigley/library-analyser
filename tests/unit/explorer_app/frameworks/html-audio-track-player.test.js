// Issue #258: the track player over an HTML audio element. It reports what the element does, for the track it loaded.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {htmlAudioTrackPlayer} from '../../../../music_explorer/frameworks/explorer/assets/app/frameworks/html-audio-track-player.js';

function audioElement({refuse} = {}) {
  const calls = [];
  const audio = {src: '', ended: false, currentTime: 0, duration: NaN, calls,
    play() { calls.push('play'); return refuse ? Promise.reject(refuse) : Promise.resolve(); },
    pause() { calls.push('pause'); }, load() { calls.push('load'); }, removeAttribute(name) { calls.push(`remove ${name}`); }};
  return audio;
}

function player(audio) {
  const reports = [];
  const port = htmlAudioTrackPlayer({audio, audioUrl: id => `/audio/${id}`, onReport: report => reports.push(report)});
  return {port, reports};
}

test('loading a track points the element at its audio and plays it; its events are reported for that track', () => {
  const audio = audioElement();
  const {port, reports} = player(audio);
  port.load('a');
  audio.onplaying();
  audio.onpause();
  audio.ended = true;
  audio.onpause();
  audio.onended();
  assert.deepEqual([audio.src, audio.calls], ['/audio/a', ['play']]);
  assert.deepEqual(reports, [{kind: 'playing', trackId: 'a'}, {kind: 'paused', trackId: 'a'}, {kind: 'ended', trackId: 'a'}],
    'the pause that comes with an ending is not a pause');
});

test('pause and resume go to the element; stop empties it and reports nothing more', () => {
  const audio = audioElement();
  const {port, reports} = player(audio);
  port.load('a');
  port.pause();
  port.resume();
  port.stop();
  audio.onpause();
  assert.deepEqual(audio.calls, ['play', 'pause', 'play', 'pause', 'remove src', 'load']);
  assert.deepEqual(reports, []);
});

test('an element error or a refused play is a failure the listener can read; an interrupted play is not', async () => {
  const audio = audioElement({refuse: Object.assign(new Error('not allowed'), {name: 'NotAllowedError'})});
  const {port, reports} = player(audio);
  port.load('a');
  await Promise.resolve();
  audio.onerror();
  assert.deepEqual(reports, [{kind: 'failed', trackId: 'a', message: 'not allowed'},
    {kind: 'failed', trackId: 'a', message: 'the file is missing or in a format this browser cannot play'}]);
  const interrupted = audioElement({refuse: Object.assign(new Error('interrupted'), {name: 'AbortError'})});
  const quiet = player(interrupted);
  quiet.port.load('b');
  await Promise.resolve();
  assert.deepEqual(quiet.reports, []);
});

test("#283: the element's progress is reported for its track, and a seek moves it", () => {
  const audio = audioElement();
  const {port, reports} = player(audio);
  audio.ontimeupdate();
  port.load('a');
  audio.ondurationchange();
  Object.assign(audio, {currentTime: 61.5, duration: 200});
  audio.ontimeupdate();
  port.seek(90);
  assert.equal(audio.currentTime, 90);
  assert.deepEqual(reports, [{kind: 'progressed', trackId: 'a', position: 0, duration: null},
    {kind: 'progressed', trackId: 'a', position: 61.5, duration: 200}], 'an unknown length is null; nothing is reported before a load');
});
