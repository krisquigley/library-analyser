// Issue #137: the chain of energy arcs a listener edits, one row per arc, played in order.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
  addEnergyArc, editEnergyArc, ARC_SHAPES, EnergyArcChainError, moveEnergyArc, NEW_ENERGY_ARC, removeEnergyArc,
} from '../../../../music_explorer/frameworks/explorer/assets/app/domain/energy-arc-chain.js';

const arc = (shape, length = '') => ({...NEW_ENERGY_ARC, shape, length});

test('the shapes an arc can take, dip included', () => {
  assert.deepEqual(ARC_SHAPES, ['steady', 'rise', 'fall', 'peak', 'dip']);
});

test('a new arc rises, with no length or range yet, at the end of the chain', () => {
  const chain = addEnergyArc(addEnergyArc([]));
  assert.deepEqual(chain, [NEW_ENERGY_ARC, NEW_ENERGY_ARC]);
  assert.deepEqual(NEW_ENERGY_ARC, {shape: 'rise', length: '', low: '', high: ''});
  assert.ok(Object.isFrozen(chain));
});

test('an arc is edited in place, its values kept as entered', () => {
  const chain = [arc('rise'), arc('fall')];
  const edited = editEnergyArc(chain, 1, {shape: 'dip', length: ' 12 ', low: '0.2'});
  assert.deepEqual(edited, [arc('rise'), {shape: 'dip', length: ' 12 ', low: '0.2', high: ''}]);
  assert.deepEqual(chain, [arc('rise'), arc('fall')], 'the chain it was given is untouched');
});

test('an edit names only an arc\'s own fields and shapes', () => {
  assert.throws(() => editEnergyArc([arc('rise')], 0, {tempo: '120'}), /Unknown energy arc field: tempo/);
  assert.throws(() => editEnergyArc([arc('rise')], 0, {shape: 'wave'}), /steady, rise, fall, peak or dip/);
});

test('arcs are removed and reordered by their place in the chain', () => {
  const chain = [arc('rise', '3'), arc('fall', '4'), arc('peak', '5')];
  assert.deepEqual(removeEnergyArc(chain, 1).map(each => each.shape), ['rise', 'peak']);
  assert.deepEqual(moveEnergyArc(chain, 2, -1).map(each => each.shape), ['rise', 'peak', 'fall']);
  assert.deepEqual(moveEnergyArc(chain, 0, 1).map(each => each.shape), ['fall', 'rise', 'peak']);
});

test('a place outside the chain, or a move past either end, is an error', () => {
  const chain = [arc('rise'), arc('fall')];
  for (const change of [() => removeEnergyArc(chain, 2), () => editEnergyArc(chain, -1, {}), () => moveEnergyArc(chain, 0, -1),
    () => moveEnergyArc(chain, 1, 1), () => moveEnergyArc(chain, 0, 2), () => removeEnergyArc(chain, 0.5)]) {
    assert.throws(change, EnergyArcChainError);
  }
});
