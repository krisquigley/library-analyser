// Issues #146 and #137: the playlist the listener is drafting, with its chain of energy arcs.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
  ARC_LENGTH_UNITS, EMPTY_PLAYLIST_DRAFT, addDraftArc, arcsSetTheLength, editDraftArc, editPlaylistDraft,
  minimumKeyStrengthApplies, moveDraftArc, playlistRecipeOf, removeDraftArc,
} from '../../../../music_explorer/frameworks/explorer/assets/app/domain/playlist-draft.js';

test('a new draft asks for ten tracks with harmonic mixing, no arcs and arc lengths in tracks', () => {
  assert.deepEqual(EMPTY_PLAYLIST_DRAFT, {
    bpmMin: '', bpmMax: '', count: '10', durationMinutes: '', harmonicMixing: true, minimumKeyStrength: '0.5',
    arcLengthUnit: 'tracks', energyArcs: [], moodHold: '',
  });
  assert.ok(Object.isFrozen(EMPTY_PLAYLIST_DRAFT));
  assert.ok(Object.isFrozen(EMPTY_PLAYLIST_DRAFT.energyArcs));
  assert.deepEqual(ARC_LENGTH_UNITS, ['tracks', 'minutes']);
});

test('editing a draft returns a new draft and leaves the old one as it was', () => {
  const edited = editPlaylistDraft(EMPTY_PLAYLIST_DRAFT, {bpmMin: '120', arcLengthUnit: 'minutes'});
  assert.equal(edited.bpmMin, '120');
  assert.equal(edited.arcLengthUnit, 'minutes');
  assert.equal(edited.count, '10');
  assert.equal(EMPTY_PLAYLIST_DRAFT.bpmMin, '');
  assert.ok(Object.isFrozen(edited));
});

test('a draft refuses a control it does not have, and its arcs are edited one arc at a time', () => {
  assert.throws(() => editPlaylistDraft(EMPTY_PLAYLIST_DRAFT, {tempo: '120'}), /Unknown playlist control: tempo/);
  assert.throws(() => editPlaylistDraft(EMPTY_PLAYLIST_DRAFT, {energyArcs: []}), /Unknown playlist control: energyArcs/);
});

test('arc lengths are in tracks or minutes, one unit for the whole chain', () => {
  assert.throws(() => editPlaylistDraft(EMPTY_PLAYLIST_DRAFT, {arcLengthUnit: 'seconds'}),
    /Arc lengths are in tracks or minutes/);
});

test('the minimum key strength applies only with harmonic mixing on', () => {
  assert.equal(minimumKeyStrengthApplies(EMPTY_PLAYLIST_DRAFT), true);
  assert.equal(minimumKeyStrengthApplies(editPlaylistDraft(EMPTY_PLAYLIST_DRAFT, {harmonicMixing: false})), false);
});

test('arcs are added, edited, moved and removed in the draft', () => {
  let draft = addDraftArc(addDraftArc(EMPTY_PLAYLIST_DRAFT));
  draft = editDraftArc(draft, 0, {shape: 'steady', length: '4'});
  draft = editDraftArc(draft, 1, {shape: 'peak', length: '6', high: '0.9'});
  assert.deepEqual(draft.energyArcs, [
    {shape: 'steady', length: '4', low: '', high: ''}, {shape: 'peak', length: '6', low: '', high: '0.9'}]);

  draft = moveDraftArc(draft, 1, -1);
  assert.deepEqual(draft.energyArcs.map(arc => arc.shape), ['peak', 'steady']);
  draft = removeDraftArc(draft, 0);
  assert.deepEqual(draft.energyArcs.map(arc => arc.shape), ['steady']);
  assert.ok(Object.isFrozen(draft));
  assert.deepEqual(EMPTY_PLAYLIST_DRAFT.energyArcs, []);
});

test('an arc edit keeps the chain rules: no unknown field, shape or place', () => {
  const draft = addDraftArc(EMPTY_PLAYLIST_DRAFT);
  assert.throws(() => editDraftArc(draft, 0, {shape: 'wave'}), /steady, rise, fall, peak or dip/);
  assert.throws(() => editDraftArc(draft, 0, {colour: 'red'}), /Unknown energy arc field: colour/);
  assert.throws(() => removeDraftArc(draft, 1), /no arc at place 1/);
});

test('arcs set the length once any arc has one', () => {
  const draft = addDraftArc(EMPTY_PLAYLIST_DRAFT);
  assert.equal(arcsSetTheLength(EMPTY_PLAYLIST_DRAFT), false);
  assert.equal(arcsSetTheLength(draft), false);
  assert.equal(arcsSetTheLength(editDraftArc(draft, 0, {length: ' 5 '})), true);
  assert.equal(arcsSetTheLength(editDraftArc(draft, 0, {length: '  '})), false);
});

test('a draft becomes the recipe for the selected start track', () => {
  let draft = editPlaylistDraft(EMPTY_PLAYLIST_DRAFT, {
    bpmMin: '120', bpmMax: '128', durationMinutes: '45', moodHold: 'happy'});
  draft = editDraftArc(addDraftArc(draft), 0, {shape: 'rise', high: '0.7'});
  assert.deepEqual(playlistRecipeOf(draft, 'track-start'), {
    startTrackId: 'track-start', bpmMin: '120', bpmMax: '128', length: {durationMinutes: '45'},
    harmonicMixing: true, minimumKeyStrength: '0.5', energyPlan: [{shape: 'rise', low: null, high: '0.7', length: null}],
    moodHold: 'happy',
  });
});

test('a draft without arcs has no energy plan, and one arc without a length spans the playlist', () => {
  assert.deepEqual(playlistRecipeOf(EMPTY_PLAYLIST_DRAFT, 'a').energyPlan, []);
  const draft = editDraftArc(addDraftArc(editPlaylistDraft(EMPTY_PLAYLIST_DRAFT, {count: '12'})), 0, {shape: 'dip'});
  const dip = playlistRecipeOf(draft, 'a');
  assert.deepEqual([dip.energyPlan, dip.length], [[{shape: 'dip', low: null, high: null, length: null}], {count: '12'}]);
});

test("a chain with lengths sets the playlist's length in the draft's unit", () => {
  let draft = editPlaylistDraft(addDraftArc(addDraftArc(EMPTY_PLAYLIST_DRAFT)), {arcLengthUnit: 'minutes'});
  draft = editDraftArc(editDraftArc(draft, 0, {length: '20'}), 1, {shape: 'fall', length: '15'});
  const recipe = playlistRecipeOf(draft, 'a');
  assert.deepEqual(recipe.length, {arcs: 'minutes'});
  assert.deepEqual(recipe.energyPlan.map(arc => arc.length), ['20', '15']);
});

test('a draft without a start track has no recipe', () => {
  assert.throws(() => playlistRecipeOf(EMPTY_PLAYLIST_DRAFT, null), /Select a start track first/);
});
