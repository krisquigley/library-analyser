// The chain of energy arcs a listener edits (#137): one row per arc, played in order.
// Values stay as entered; the server validates lengths and ranges and owns their messages.

export const ARC_SHAPES = Object.freeze(['steady', 'rise', 'fall', 'peak', 'dip']);

export const NEW_ENERGY_ARC = Object.freeze({shape: 'rise', length: '', low: '', high: ''});

export class EnergyArcChainError extends Error {}

export function addEnergyArc(chain) {
  return Object.freeze([...chain, NEW_ENERGY_ARC]);
}

export function removeEnergyArc(chain, place) {
  checkPlace(chain, place);
  return Object.freeze(chain.filter((_, index) => index !== place));
}

export function moveEnergyArc(chain, place, offset) {
  checkPlace(chain, place);
  if (Math.abs(offset) !== 1) throw new EnergyArcChainError('An arc moves one place at a time');
  checkPlace(chain, place + offset);
  const moved = [...chain];
  [moved[place], moved[place + offset]] = [moved[place + offset], moved[place]];
  return Object.freeze(moved);
}

export function editEnergyArc(chain, place, changes) {
  checkPlace(chain, place);
  const unknown = Object.keys(changes).find(field => !Object.hasOwn(NEW_ENERGY_ARC, field));
  if (unknown) throw new EnergyArcChainError(`Unknown energy arc field: ${unknown}`);
  if (Object.hasOwn(changes, 'shape') && !ARC_SHAPES.includes(changes.shape)) {
    throw new EnergyArcChainError('An energy arc is steady, rise, fall, peak or dip');
  }
  return Object.freeze(chain.map((arc, index) => (index === place ? Object.freeze({...arc, ...changes}) : arc)));
}

function checkPlace(chain, place) {
  if (!Number.isInteger(place) || place < 0 || place >= chain.length) {
    throw new EnergyArcChainError(`There is no arc at place ${place} in a chain of ${chain.length}`);
  }
}
