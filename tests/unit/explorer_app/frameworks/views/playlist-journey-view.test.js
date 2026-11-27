// Issue #294: the journey chart under the hand-built playlist: a lane per measure, each with a toggle, and a readout of
// the track under the pointer.
import {test, beforeEach} from 'node:test';
import assert from 'node:assert/strict';
import {playlistJourneyView} from '../../../../../music_explorer/frameworks/explorer/assets/app/frameworks/views/playlist-journey-view.js';
import {byTag, descendants, fakeElement, installFakeDocument} from '../fake-document.js';

let roots, drawn;
beforeEach(() => {
  roots = installFakeDocument(['playlist-journey']);
  drawn = [];
  const create = globalThis.document.createElement;
  globalThis.document.createElement = tag => {
    const made = create(tag);
    if (tag === 'canvas') Object.assign(made, {clientWidth: 400,
      getBoundingClientRect: () => ({left: 10, width: 400}),
      getContext: () => new Proxy({}, {get: (_, name) => (typeof name === 'string' && /^[a-z]/.test(name) && name !== 'canvas'
        ? (...args) => drawn.push([name, ...args]) : undefined), set: (_, name, value) => { drawn.push(['set', name, value]); return true; }})});
    return made;
  };
});

const lane = (measure, label, range, levels) => ({measure, label, range,
  steps: levels.map((level, place) => ({from: place / levels.length, to: (place + 1) / levels.length, level}))});
const MODEL = {hidden: false, caption: 'Your playlist over 6:40',
  lanes: [lane('bpm', 'BPM', '120.0–130.0', [0, 1]), lane('key', 'Key (Camelot)', '1–12', [0.5, null]),
    lane('arousal', 'Arousal', '3.0–5.0', [0.5, 0.5]), lane('valence', 'Valence', 'unknown', [null, null])],
  ticks: [{at: 0, text: '0:00'}, {at: 0.5, text: '3:20'}],
  stops: [{from: 0, to: 0.5, readout: 'First track'}, {from: 0.5, to: 1, readout: 'Second track'}]};

const host = () => roots['playlist-journey'];
const byId = id => descendants(host()).find(node => node.id === id);
const toggles = () => byTag(host(), 'input');

test('the chart has a heading, its caption, a toggle per lane naming its range, a canvas and a readout', () => {
  const view = playlistJourneyView();
  view.show(MODEL);
  assert.equal(host().hidden, false);
  assert.equal(byId('playlist-journey-heading').textContent, 'Journey');
  assert.equal(byId('playlist-journey-caption').textContent, 'Your playlist over 6:40');
  assert.deepEqual(toggles().map(box => [box.type, box.id, box.checked]), [['checkbox', 'journey-show-bpm', true],
    ['checkbox', 'journey-show-key', true], ['checkbox', 'journey-show-arousal', true], ['checkbox', 'journey-show-valence', true]]);
  assert.deepEqual(byTag(host(), 'label').map(label => label.textContent), ['BPM 120.0–130.0', 'Key (Camelot) 1–12',
    'Arousal 3.0–5.0', 'Valence unknown']);
  const canvas = byId('playlist-journey-chart');
  assert.equal(canvas.getAttribute('role'), 'img');
  assert.match(canvas.getAttribute('aria-label'), /BPM, key, arousal and valence/);
  assert.ok(drawn.some(([name]) => name === 'lineTo'), 'the lanes are drawn');
  assert.ok(drawn.some(([name, text]) => name === 'fillText' && text === 'BPM'), 'each lane is named on the chart');
});

test('a toggle hides its lane and shows it again, and the chart grows and shrinks with the lanes shown', () => {
  const view = playlistJourneyView();
  view.show(MODEL);
  const canvas = byId('playlist-journey-chart');
  const tall = canvas.height;
  const [bpm] = toggles();
  bpm.checked = false; drawn.length = 0; bpm.onchange();
  assert.ok(canvas.height < tall);
  assert.ok(!drawn.some(([name, text]) => name === 'fillText' && text === 'BPM'), 'a hidden lane is not drawn');
  view.show(MODEL);
  assert.equal(toggles()[0].checked, false, 'what the listener hid stays hidden when the playlist changes');
  bpm.checked = true; bpm.onchange();
  assert.equal(canvas.height, tall);
});

test('the readout names the track under the pointer, and empties when it leaves', () => {
  const view = playlistJourneyView();
  view.show(MODEL);
  const canvas = byId('playlist-journey-chart');
  const readout = byId('playlist-journey-readout');
  canvas.onpointermove({clientX: 10 + 96 + 250});
  assert.equal(readout.textContent, 'Second track', 'the plot starts after the lane names');
  canvas.onpointermove({clientX: 10 + 96 + 20});
  assert.equal(readout.textContent, 'First track');
  canvas.onpointermove({clientX: 10 + 40});
  assert.equal(readout.textContent, '', 'over the lane names, no track');
  canvas.onpointerleave();
  assert.equal(readout.textContent, '');
});

test('a journey not worth showing hides the chart, and a page without it is left alone', () => {
  const view = playlistJourneyView();
  view.show({...MODEL, hidden: true});
  assert.equal(host().hidden, true);
  installFakeDocument([]);
  playlistJourneyView().show(MODEL);
});
