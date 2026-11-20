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

test('hover labels escape text and give each axis its raw value and scale', () => {
  const hovered = {label: '<b>Song</b>', axis: {x: axis(0.25, 'v'), y: axis(0.5, 'a'), z: {raw: 120, scale: 'bpm', label: 'BPM'}},
    moodScore: {label: 'calm', raw: 0.6}};
  assert.equal(nodeLabel(hovered),
    '&lt;b&gt;Song&lt;/b&gt;<br>valence 0.3 (v)<br>arousal 0.5 (a)<br>BPM 120.0 (bpm)<br>calm 0.6 / 1');
  assert.match(nodeLabel({...hovered, moodScore: null}), /Selected mood score unavailable$/);
  assert.equal(linkLabel({score: 0.5, explanation: 'tempo & key'}), 'score 0.5; tempo &amp; key; groups 0');
});

test('a negative relatedness score is as faint as none, and the legend says what opacity means', () => {
  assert.equal(relatednessLinkAlpha({score: -2}), 0.18);
  assert.match(graphRelatednessLegend(), /Link alpha reflects axis-independent relatedness strength.*higher-score links are more opaque/);
});
