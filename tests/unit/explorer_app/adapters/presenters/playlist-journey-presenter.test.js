// Issue #294: the hand-built playlist's journey as the chart shows it: a lane per measure on a shared time axis.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {playlistJourneyViewModel} from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/presenters/playlist-journey-presenter.js';

const track = (trackId, fields = {}) => ({trackId, title: 'Title ' + trackId, artist: 'Synthetic', bpm: 120, key: 'A minor',
  camelot: '8A', arousal: 4, valence: 5, energyTarget: null, durationSeconds: 100, ...fields});
const previewed = (...tracks) => ({trackIds: tracks.map(each => each.trackId), tracks, transitions: []});

test('each measure is a lane with its own range; each track a step across its share of the time', () => {
  const model = playlistJourneyViewModel({trackIds: ['a', 'b'], previewed: previewed(track('a'),
    track('b', {bpm: 130, camelot: '11B', arousal: null, valence: 6, durationSeconds: 300}))});
  assert.equal(model.hidden, false);
  assert.equal(model.caption, 'Your playlist over 6:40');
  assert.deepEqual(model.lanes.map(lane => [lane.measure, lane.label, lane.range]), [
    ['bpm', 'BPM', '120.0–130.0'], ['key', 'Key (Camelot)', '1–12'], ['arousal', 'Arousal', '3.0–5.0'],
    ['valence', 'Valence', '5.0–6.0']]);
  assert.deepEqual(model.lanes[0].steps, [{from: 0, to: 0.25, level: 0}, {from: 0.25, to: 1, level: 1}]);
  assert.deepEqual(model.lanes[1].steps.map(step => step.level), [7 / 11, 10 / 11]);
  assert.deepEqual(model.lanes[2].steps.map(step => step.level), [0.5, null], 'one known arousal sits mid-lane; none is a gap');
  assert.deepEqual(model.ticks, [{at: 0, text: '0:00'}, {at: 0.15, text: '1:00'}, {at: 0.3, text: '2:00'}, {at: 0.45, text: '3:00'},
    {at: 0.6, text: '4:00'}, {at: 0.75, text: '5:00'}, {at: 0.9, text: '6:00'}]);
  assert.deepEqual(model.stops, [
    {from: 0, to: 0.25, readout: 'Synthetic – Title a · 0:00–1:40 · 120.0 BPM · Key A minor (8A) · Arousal 4.0 · Valence 5.0'},
    {from: 0.25, to: 1, readout: 'Synthetic – Title b · 1:40–6:40 · 130.0 BPM · Key A minor (11B) · Arousal — · Valence 6.0'}]);
});

test('a lane with no known value says so; a journey of fewer than two tracks is not shown', () => {
  const model = playlistJourneyViewModel({trackIds: ['a', 'b'], previewed: previewed(track('a', {valence: null}),
    track('b', {valence: null, key: null, camelot: null}))});
  assert.deepEqual([model.lanes[3].range, model.lanes[3].steps.map(step => step.level)], ['unknown', [null, null]]);
  assert.match(model.stops[1].readout, / · Key — · /);
  assert.equal(playlistJourneyViewModel({trackIds: ['a'], previewed: previewed(track('a'))}).hidden, true);
  assert.equal(playlistJourneyViewModel({trackIds: [], previewed: null}).hidden, true);
});

test('lengths the library does not know are said to be estimated', () => {
  const model = playlistJourneyViewModel({trackIds: ['a', 'b'], previewed: previewed(track('a'), track('b', {durationSeconds: null}))});
  assert.equal(model.caption, 'Your playlist over 3:20 · lengths not known are shown as the average');
});

test('a long playlist has fewer, wider ticks', () => {
  const model = playlistJourneyViewModel({trackIds: ['a', 'b'], previewed: previewed(track('a', {durationSeconds: 1800}),
    track('b', {durationSeconds: 1800}))});
  assert.deepEqual(model.ticks.map(tick => tick.text), ['0:00', '10:00', '20:00', '30:00', '40:00', '50:00', '1:00:00']);
});
