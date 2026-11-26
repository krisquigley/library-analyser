// Issue #282: the BPM difference floats over the middle of each of the selection's links, and never takes pointer input.
import {test, beforeEach} from 'node:test';
import assert from 'node:assert/strict';
import {createLinkLabels} from '../../../../../music_explorer/frameworks/explorer/assets/app/frameworks/graph-scene/link-labels.js';
import {fakeElement, installFakeDocument} from '../fake-document.js';

beforeEach(() => { installFakeDocument([]); });

const viewport = () => Object.assign(fakeElement('div'), {clientWidth: 800, clientHeight: 600});
const graph = {graph2ScreenCoords: (x, y) => ({x, y})};
const nodes = [{id: 'a', x: 100, y: 200, z: 0}, {id: 'b', x: 300, y: 400, z: 50}, {id: 'c', x: 1700, y: 0, z: 0}];

test('each label sits over the middle of its link, hidden when off screen, and is replaced by the next set', () => {
  const labels = createLinkLabels();
  const host = viewport();
  labels.show(host, [{sourceId: 'a', targetId: 'b', text: '+3.5 BPM'}, {sourceId: 'a', targetId: 'c', text: '−2 BPM'}]);
  assert.deepEqual(host.children.map(label => [label.tagName, label.className, label.textContent]),
    [['SPAN', 'graph-link-label', '+3.5 BPM'], ['SPAN', 'graph-link-label', '−2 BPM']]);
  labels.place(graph, host, nodes);
  assert.deepEqual(host.children.map(label => [label.style.transform, label.style.display]), [
    ['translate(200px,300px) translate(-50%,-50%)', ''], ['translate(900px,100px) translate(-50%,-50%)', 'none']]);
  labels.show(host, []);
  assert.deepEqual(host.children, []);
});

test('a label whose link the graph no longer shows is hidden', () => {
  const labels = createLinkLabels();
  const host = viewport();
  labels.show(host, [{sourceId: 'a', targetId: 'gone', text: '0 BPM'}]);
  labels.place(graph, host, nodes);
  assert.equal(host.children[0].style.display, 'none');
});
