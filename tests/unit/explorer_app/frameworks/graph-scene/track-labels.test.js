// Issue #243: the labels float above their tracks' nodes on the screen; only their buttons take pointer input (#276).
import {test, beforeEach} from 'node:test';
import assert from 'node:assert/strict';
import {createTrackLabels} from '../../../../../music_explorer/frameworks/explorer/assets/app/frameworks/graph-scene/track-labels.js';
import {fakeElement, installFakeDocument} from '../fake-document.js';

beforeEach(() => { installFakeDocument([]); });

const viewport = () => Object.assign(fakeElement('div'), {clientWidth: 800, clientHeight: 600});
const graph = {graph2ScreenCoords: (x, y) => ({x, y})};
const nodes = [{id: 'a', x: 100, y: 200, z: 0}, {id: 'b', x: 900, y: 50, z: 0}];
const labelText = label => label.children.find(part => part.className === 'graph-track-label-text').textContent;
const playButton = label => label.children.find(part => part.className === 'graph-track-label-play');
const addButton = label => label.children.find(part => part.className === 'graph-track-label-add');
const shown = [{trackId: 'a', text: 'Alpha — Synthetic', selected: true}, {trackId: 'b', text: 'Beta — Synthetic', selected: false}];
const idle = {text: '▶', verb: 'Play', pressed: false};
const playingA = {activeTrackId: 'a', activeButton: {text: '❚❚', verb: 'Pause', pressed: true}, idleButton: idle};

test('labels are text above their nodes, hidden off screen, and replaced by the next set', () => {
  const labels = createTrackLabels({onPlayRequested: () => {}, onAddRequested: () => {}});
  const host = viewport();
  labels.show(host, [{trackId: 'a', text: '<b>Alpha</b> — Synthetic', selected: true}, {trackId: 'b', text: 'Beta — Synthetic', selected: false}]);
  assert.deepEqual(host.children.map(label => [label.className, labelText(label)]),
    [['graph-track-label selected', '<b>Alpha</b> — Synthetic'], ['graph-track-label', 'Beta — Synthetic']]);
  labels.place(graph, host, nodes);
  assert.equal(host.children[0].style.transform, 'translate(100px,200px) translate(-50%,calc(-100% - 10px))');
  assert.deepEqual(host.children.map(label => label.style.display), ['', 'none'], 'b is off screen');
  labels.show(host, []);
  assert.deepEqual(host.children, []);
});

test('a label whose track the graph no longer shows is hidden', () => {
  const labels = createTrackLabels({onPlayRequested: () => {}, onAddRequested: () => {}});
  const host = viewport();
  labels.show(host, [{trackId: 'gone', text: 'Gone', selected: false}]);
  labels.place(graph, host, nodes);
  assert.equal(host.children[0].style.display, 'none');
});

test('#276: every label has a play button that asks for its own track', () => {
  const asked = [];
  const labels = createTrackLabels({onPlayRequested: trackId => asked.push(trackId), onAddRequested: () => {}});
  const host = viewport();
  labels.show(host, shown);
  const buttons = host.children.map(playButton);
  assert.deepEqual(buttons.map(button => [button.tagName, button.type, button.textContent, button.getAttribute('aria-label')]),
    [['BUTTON', 'button', '▶', 'Play Alpha — Synthetic'], ['BUTTON', 'button', '▶', 'Play Beta — Synthetic']]);
  buttons[1].onclick();
  buttons[0].onclick();
  assert.deepEqual(asked, ['b', 'a']);
});

test("#276: the playing track's button offers pause; labels shown later match the playback", () => {
  const labels = createTrackLabels({onPlayRequested: () => {}, onAddRequested: () => {}});
  const host = viewport();
  labels.show(host, shown);
  labels.showPlayback(playingA);
  const looks = () => host.children.map(label => [playButton(label).textContent, playButton(label).getAttribute('aria-label'),
    playButton(label).getAttribute('aria-pressed')]);
  assert.deepEqual(looks(), [['❚❚', 'Pause Alpha — Synthetic', 'true'], ['▶', 'Play Beta — Synthetic', 'false']]);
  labels.show(host, [...shown].reverse());
  assert.deepEqual(looks(), [['▶', 'Play Beta — Synthetic', 'false'], ['❚❚', 'Pause Alpha — Synthetic', 'true']]);
});

test("#278: a neighbour's label has a + that asks to add it; the selected track's has none", () => {
  const added = [];
  const labels = createTrackLabels({onPlayRequested: () => {}, onAddRequested: trackId => added.push(trackId)});
  const host = viewport();
  labels.show(host, shown);
  assert.equal(addButton(host.children[0]), undefined);
  const add = addButton(host.children[1]);
  assert.deepEqual([add.tagName, add.type, add.textContent, add.getAttribute('aria-label')],
    ['BUTTON', 'button', '+', 'Add Beta — Synthetic to your playlist']);
  assert.deepEqual(host.children[1].children.map(part => part.className),
    ['graph-track-label-play', 'graph-track-label-text', 'graph-track-label-add']);
  add.onclick();
  assert.deepEqual(added, ['b']);
});

test('#278: a neighbour already in the playlist shows a tick, and labels shown later match the playlist', () => {
  const added = [];
  const labels = createTrackLabels({onPlayRequested: () => {}, onAddRequested: trackId => added.push(trackId)});
  const host = viewport();
  labels.show(host, shown);
  labels.showPlaylist(['a', 'b']);
  const look = () => [addButton(host.children[1]).textContent, addButton(host.children[1]).getAttribute('aria-label')];
  assert.deepEqual(look(), ['✓', 'Go to Beta — Synthetic, already in your playlist']);
  addButton(host.children[1]).onclick();
  assert.deepEqual(added, ['b'], 'it still asks, and the playlist only selects it');
  labels.show(host, [{...shown[0], selected: false}, {...shown[1], selected: true}]);
  assert.deepEqual([addButton(host.children[0]).textContent, addButton(host.children[1])], ['✓', undefined]);
  labels.showPlaylist([]);
  assert.equal(addButton(host.children[0]).textContent, '+');
});
