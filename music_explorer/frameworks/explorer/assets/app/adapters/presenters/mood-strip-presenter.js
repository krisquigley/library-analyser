// How the mood strip shows its marks (#146): along a padded line, ties stacked alternately above and below
// so every mark stays visible, with a readout for each.

import {displayNumber} from '../../domain/display-number.js';

const HEIGHT = 70;
const BASELINE = 35;
const PADDING = 14;
const STACK_STEP = 5;
const UNMEASURED_WIDTH = 600;
const EMPTY_READOUT = 'No visible tracks have this selected mood score; tracks without it have no mark.';

export function moodMarkDescription(mark) {
  return `${mark.label}: ${mark.moodLabel} ${displayNumber(mark.score)} / 1 (raw sigmoid mean score)`;
}

export function moodStripViewModel(marks, measuredWidth) {
  const width = Math.max(1, Math.floor(measuredWidth || UNMEASURED_WIDTH));
  const placed = stacked(marks.map(mark => ({...mark, x: PADDING + (width - 2 * PADDING) * mark.position})));
  const selected = placed.findIndex(mark => mark.selected);
  return {
    width, height: HEIGHT, baseline: BASELINE, padding: PADDING,
    marks: placed.map(({x, y, selected: isSelected}) => ({x, y, selected: isSelected})),
    pickerMax: Math.max(0, placed.length - 1),
    disabled: !placed.length,
    index: Math.max(0, selected),
    readouts: placed.map((mark, index) => `${index + 1} / ${placed.length}: ${moodMarkDescription(mark)}`),
    emptyReadout: EMPTY_READOUT,
  };
}

export function nearestMarkIndex(view, pixel) {
  let nearest = 0;
  for (let index = 1; index < view.marks.length; index++) {
    if (Math.abs(view.marks[index].x - pixel) < Math.abs(view.marks[nearest].x - pixel)) nearest = index;
  }
  return nearest;
}

function stacked(marks) {
  const levels = new Map();
  return marks.map(mark => {
    const pixel = Math.round(mark.x);
    const level = levels.get(pixel) || 0;
    levels.set(pixel, level + 1);
    const offset = STACK_STEP + Math.floor(level / 2) * STACK_STEP;
    const y = level % 2 ? BASELINE + offset : BASELINE - offset;
    return {...mark, y: Math.max(STACK_STEP, Math.min(HEIGHT - STACK_STEP, y))};
  });
}
