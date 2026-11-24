// Issue #243: the labels float above their tracks' nodes on the screen and never take pointer input.
import {test, beforeEach} from 'node:test';
import assert from 'node:assert/strict';
import {createTrackLabels} from '../../../../../music_explorer/frameworks/explorer/assets/app/frameworks/graph-scene/track-labels.js';
import {fakeElement, installFakeDocument} from '../fake-document.js';

beforeEach(() => { installFakeDocument([]); });

const viewport = () => Object.assign(fakeElement('div'), {clientWidth: 800, clientHeight: 600});
const graph = {graph2ScreenCoords: (x, y) => ({x, y})};
const nodes = [{id: 'a', x: 100, y: 200, z: 0}, {id: 'b', x: 900, y: 50, z: 0}];

test('labels are text above their nodes, hidden off screen, and replaced by the next set', () => {
  const labels = createTrackLabels();
  const host = viewport();
  labels.show(host, [{trackId: 'a', text: '<b>Alpha</b> — Synthetic', selected: true}, {trackId: 'b', text: 'Beta — Synthetic', selected: false}]);
  assert.deepEqual(host.children.map(label => [label.className, label.textContent]),
    [['graph-track-label selected', '<b>Alpha</b> — Synthetic'], ['graph-track-label', 'Beta — Synthetic']]);
  labels.place(graph, host, nodes);
  assert.equal(host.children[0].style.transform, 'translate(100px,200px) translate(-50%,calc(-100% - 10px))');
  assert.deepEqual(host.children.map(label => label.style.display), ['', 'none'], 'b is off screen');
  labels.show(host, []);
  assert.deepEqual(host.children, []);
});

test('a label whose track the graph no longer shows is hidden', () => {
  const labels = createTrackLabels();
  const host = viewport();
  labels.show(host, [{trackId: 'gone', text: 'Gone', selected: false}]);
  labels.place(graph, host, nodes);
  assert.equal(host.children[0].style.display, 'none');
});
