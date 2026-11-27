// Issue #146: the graph's axes, legends and hover labels.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
  graphAxisSpec, graphColorLegend, graphRelatednessLegend, linkLabel, nodeLabel, relatednessLinkAlpha, relatednessLinkColor,
} from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/presenters/graph-scene-presenter.js';

const axis = (raw, scale = 'native') => ({raw, scale});
const node = (x, y, z, raws) => ({x, y, z, axis: raws && {x: axis(raws[0]), y: axis(raws[1]), z: {...axis(raws[2]), label: 'BPM'}}});

test('the axes start outside the nodes and reach past them, labelled with the raw range', () => {
  const axes = graphAxisSpec([node(0, 10, 100, [-0.5, 0.2, 100]), node(90, 40, 120, [0.75, 0.9, 120]), node(NaN, 0, 0)]);
  assert.deepEqual(axes.map(a => [a.key, a.label, a.color]),
    [['x', 'X valence (native)', '#ff7777'], ['y', 'Y arousal (native)', '#76dfa0'], ['z', 'Z BPM', '#84b9ff']]);
  assert.deepEqual(axes[0].start, {x: -18, y: -8, z: 82});
  assert.deepEqual(axes[0].end, {x: 108, y: -8, z: 82});
  assert.deepEqual(axes[1].end, {x: -18, y: 58, z: 82});
  assert.deepEqual(axes.map(a => a.references), [['-0.5', '0.8'], ['0.2', '0.9'], ['100.0', '120.0']]);
});

test('an axis is at least 36 long, and without raw values its references come from the display units', () => {
  const axes = graphAxisSpec([node(720, 360, 36)]);
  assert.deepEqual(axes[0].end.x, axes[0].start.x + 36);
  assert.deepEqual(axes.map(a => a.references), [['2.0', '2.0'], ['1.0', '1.0'], ['1.0', '1.0']]);
  assert.deepEqual(graphAxisSpec([]), []);
});

test('the axes depend on where the nodes are, never on their order', () => {
  const nodes = [node(0, 10, 100, [-0.5, 0.2, 100]), node(90, 40, 120, [0.75, 0.9, 120])];
  assert.deepEqual(graphAxisSpec([...nodes].reverse()), graphAxisSpec(nodes));
});

test('the colour legend gives each native range, or says there is none', () => {
  assert.equal(graphColorLegend({colorRanges: {valence: {min: -0.5, max: 0.75}, arousal: [0.1, 1.9]}}),
    'Color relative to this library: valence blue → orange/red (-0.5 to 0.8 native); arousal dark/dim → bright (0.1 to 1.9 native). Selected node is larger.');
  assert.match(graphColorLegend({}), /valence blue → orange\/red \(no positioned values native\)/);
});

test('link opacity follows the clamped relatedness score', () => {
  assert.deepEqual([relatednessLinkAlpha({score: 0}), relatednessLinkAlpha({score: 1}), relatednessLinkAlpha({score: 7}),
    relatednessLinkAlpha({score: 'x'}), relatednessLinkAlpha(null)], [0.18, 0.72, 0.72, 0.18, 0.18]);
  assert.equal(relatednessLinkColor({score: 0.5}), 'rgba(240,240,240,0.45)');
  assert.match(graphRelatednessLegend(), /higher-score links are more opaque/);
});

test('#291: the hover card gives the track, its BPM and key, and its mood values, escaped', () => {
  const hovered = {label: '<b>Song</b>', axis: {x: axis(0.25, 'v'), y: axis(0.5, 'a'), z: {raw: 120, scale: 'bpm', label: 'BPM'}},
    moodScore: {label: 'calm', raw: 0.6}, key: 'A minor'};
  assert.equal(nodeLabel(hovered), '<div class="node-hover"><strong class="node-hover-title">&lt;b&gt;Song&lt;/b&gt;</strong>'
    + '<span class="node-hover-facts"><span>120.0 BPM</span><span>Key A minor</span></span>'
    + '<span class="node-hover-moods"><span>Valence <b>0.3</b></span><span>Arousal <b>0.5</b></span><span>calm <b>0.6</b></span></span></div>');
  const unknown = nodeLabel({...hovered, moodScore: null, key: '<i>D</i>'});
  assert.match(unknown, /<span>Key &lt;i&gt;D&lt;\/i&gt;<\/span>/, 'a key the listener typed is escaped');
  assert.match(unknown, /<span>Arousal <b>0.5<\/b><\/span><\/span><\/div>$/, 'no mood score, no mood value');
  assert.match(nodeLabel({...hovered, key: null}), /<span>Key unknown<\/span>/);
  assert.equal(linkLabel({score: 0.5, explanation: 'tempo & key'}), 'score 0.5; tempo &amp; key; groups 0');
});

test('a negative relatedness score is as faint as none, and the legend says what opacity means', () => {
  assert.equal(relatednessLinkAlpha({score: -2}), 0.18);
  assert.match(graphRelatednessLegend(), /Link alpha reflects axis-independent relatedness strength.*higher-score links are more opaque/);
});

test('#243: outside the selected track\'s neighbourhood, nodes and links are very dim; inside, they keep their colours', async () => {
  const {graphNeighbourFocus, focusedNodeColor, focusedLinkColor, relatednessLinkColor: linkColour} =
    await import('../../../../../music_explorer/frameworks/explorer/assets/app/adapters/presenters/graph-scene-presenter.js');
  const [a, b, c] = ['a', 'b', 'c'].map(id => ({id, color: `hsl(${id.charCodeAt(0)} 50% 50%)`}));
  const near = {source: a, target: b, score: 0.8}, far = {source: 'b', target: 'c', score: 0.8};
  const focus = graphNeighbourFocus({nodes: [a, b, c], links: [near, far]}, 'a');
  assert.deepEqual([a, b, c].map(focusedNodeColor(focus)), [a.color, b.color, 'rgba(120,135,160,0.1)']);
  assert.deepEqual([far].map(focusedLinkColor(focus, [a, b, c])), ['rgba(240,240,240,0.03)']);
  const none = graphNeighbourFocus({nodes: [a, b, c], links: [near, far]}, null);
  assert.deepEqual([c].map(focusedNodeColor(none)), [c.color]);
  assert.deepEqual([near, far].map(focusedLinkColor(none, [a, b, c])), [linkColour(near), linkColour(far)]);
});

test("a track's neighbourhood is where the shown tracks linked to it are placed (#267)", async () => {
  const {graphNeighbourPositions} = await import('../../../../../music_explorer/frameworks/explorer/assets/app/adapters/presenters/graph-scene-presenter.js');
  const placed = (id, fx) => ({id, fx, fy: 0, fz: 0});
  const visible = {nodes: [placed('a', 0), placed('b', 10), placed('c', 20), placed('d', 30)],
    links: [{source: 'a', target: 'b'}, {source: {id: 'c'}, target: {id: 'a'}}, {source: 'b', target: 'd'}]};
  assert.deepEqual(graphNeighbourPositions(visible, 'a'), [{x: 10, y: 0, z: 0}, {x: 20, y: 0, z: 0}]);
  assert.deepEqual(graphNeighbourPositions(visible, 'missing'), []);
});

const presenter = () => import('../../../../../music_explorer/frameworks/explorer/assets/app/adapters/presenters/graph-scene-presenter.js');

test("#273: a selected track's link runs blue to red as the neighbour's valence is lower or higher", async () => {
  const {neighbourDifferenceColor} = await presenter();
  const still = {arousal: 0, bpm: 0};
  assert.deepEqual([-0.25, -1, 0, 0.25, 0.1].map(valence => neighbourDifferenceColor({valence, ...still})),
    ['rgba(128,145,179,0.9)', 'rgba(128,145,179,0.9)', 'rgba(170,128,179,0.9)', 'rgba(179,128,128,0.9)',
      'rgba(179,128,163,0.9)']);
});

test('#282: the further apart in arousal, the more vivid the link; BPM plays no part', async () => {
  const {neighbourDifferenceColor} = await presenter();
  assert.deepEqual([[0.25, 0], [-0.25, 1], [0.5, 0], [0.125, 0], [0, 1]].map(([arousal, bpm]) =>
    neighbourDifferenceColor({valence: 0.25, arousal, bpm})),
  ['rgba(255,51,51,0.9)', 'rgba(255,51,51,0.9)', 'rgba(255,51,51,0.9)', 'rgba(217,89,89,0.9)', 'rgba(179,128,128,0.9)']);
});

test("#282: each of the selection's links is labelled with the neighbour's BPM less the selected track's", async () => {
  const {graphNeighbourFocus, selectionLinkLabels} = await presenter();
  const placed = (id, bpm) => ({id, axis: {x: {raw: 0}, y: {raw: 0}, z: {raw: bpm}}});
  const nodes = [placed('a', 120), placed('b', 123.46), placed('c', 118), placed('d', 120.04), placed('e', null)];
  const links = [{source: nodes[1], target: nodes[0]}, {source: 'a', target: 'c'}, {source: 'a', target: 'd'},
    {source: 'a', target: 'e'}, {source: 'b', target: 'c'}];
  const focus = graphNeighbourFocus({nodes, links}, 'a');
  assert.deepEqual(selectionLinkLabels(focus, nodes, links), [
    {sourceId: 'b', targetId: 'a', text: '+3.5 BPM'}, {sourceId: 'a', targetId: 'c', text: '−2 BPM'},
    {sourceId: 'a', targetId: 'd', text: '0 BPM'}]);
  assert.deepEqual(selectionLinkLabels(graphNeighbourFocus({nodes, links}, null), nodes, links), []);
});

test("#273: the selection's links compare each neighbour with the selected track across the library's spans", async () => {
  const {graphNeighbourFocus, focusedLinkColor, neighbourDifferenceColor} = await presenter();
  const placed = (id, valence, arousal, bpm) => ({id, axis: {x: {raw: valence}, y: {raw: arousal}, z: {raw: bpm}}});
  const nodes = [placed('a', 0.5, 0, 100), placed('b', 0.25, 0, 100), placed('c', 0.5, 0.5, 100), placed('d', 1, 1, 200)];
  const toB = {source: nodes[1], target: nodes[0], score: 1}, toC = {source: 'a', target: 'c', score: 0.2};
  const focus = graphNeighbourFocus({nodes, links: [toB, toC]}, 'a');
  assert.deepEqual([toB, toC].map(focusedLinkColor(focus, nodes)), [
    neighbourDifferenceColor({valence: -0.25, arousal: 0, bpm: 0}),
    neighbourDifferenceColor({valence: 0, arousal: 0.5, bpm: 0})]);
});

test("#273: the selection's links are as thick as they are related; other links keep their width", async () => {
  const {graphNeighbourFocus, focusedLinkWidth, relatednessLinkWidth} = await presenter();
  const nodes = ['a', 'b', 'c'].map(id => ({id}));
  const strong = {source: 'a', target: 'b', score: 1}, weak = {source: 'a', target: 'c', score: 0.25};
  const far = {source: 'b', target: 'c', score: 0.5}, odd = {source: 'a', target: 'c', score: 'x'};
  const focus = graphNeighbourFocus({nodes, links: [strong, weak, far]}, 'a');
  assert.deepEqual([strong, weak, odd, far].map(focusedLinkWidth(focus)), [5, 2, 1, 1.5]);
  assert.deepEqual([strong, far, {score: -1}].map(relatednessLinkWidth), [2, 1.5, 1]);
  const none = graphNeighbourFocus({nodes, links: [strong]}, null);
  assert.deepEqual([strong].map(focusedLinkWidth(none)), [2]);
});
