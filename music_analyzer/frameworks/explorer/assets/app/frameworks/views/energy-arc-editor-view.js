// The energy arc editor inside the Download M3U controls (#137): one row per arc, in play order.
// A chain of the same size is updated in place, so the field the listener is in keeps its focus.
// #234: each row is a collapsible accordion item summed up in one line; a new arc opens, the others keep their state.

const ENERGY_LEVEL_SCALE = "in arousal as the graph shows it (its vertical axis); left blank, it follows the tracks in your BPM range";
const ARC_FIELDS = Object.freeze(['shape', 'length', 'low', 'high']);
const ARC_FIELD_CAPTIONS = Object.freeze({shape: 'Shape', length: 'Length', low: 'Energy low', high: 'Energy high'});

export function energyArcEditorView({onArcAdded, onArcRemoved, onArcMoved, onArcEdited}) {
  let rows = null;
  let rowControls = [];
  let shapeChoices = [];
  let arousalRange = null;

  function build(unitControl, viewModel) {
    shapeChoices = viewModel.arcShapeChoices;
    rows = arcElement('div', {id: 'm3u-arc-rows'});
    const add = arcElement('button', {id: 'm3u-add-arc', type: 'button'});
    setArcText(add, 'Add energy arc');
    add.onclick = () => onArcAdded();
    arousalRange = arcElement('p', {id: 'm3u-arousal-range', className: 'muted'});
    showArousalRange(viewModel.arousalRange);
    const fieldset = arcElement('fieldset', {id: 'm3u-energy-arcs'});
    fieldset.append(setArcText(document.createElement('legend'), 'Energy arcs'),
      arcLabel(unitControl, 'Length in'), unitControl, arousalRange, rows, add);
    show(viewModel.arcs, viewModel.arcLengthUnit);
    return fieldset;
  }

  function show(arcs, unit) {
    if (!rows) return;
    if (rowControls.length !== arcs.length) {
      const wasOpen = rowControls.map(controls => controls.row.open);
      rowControls = arcs.map((arc, place) => arcRowControls(place));
      rowControls.forEach((controls, place) => { controls.row.open = wasOpen[place] ?? true; });
      rows.replaceChildren(...rowControls.map(controls => controls.row));
    }
    arcs.forEach((arc, place) => syncRow(rowControls[place], arc, unit));
  }

  function arcRowControls(place) {
    const fields = {
      shape: arcSelect(`m3u-arc-shape-${place}`, shapeChoices, `Arc ${place + 1} shape`),
      length: arcElement('input', {id: `m3u-arc-length-${place}`, type: 'number', min: '0'}),
      low: energyLevel(`m3u-arc-low-${place}`, `How low arc ${place + 1} goes, ${ENERGY_LEVEL_SCALE}`),
      high: energyLevel(`m3u-arc-high-${place}`, `How high arc ${place + 1} goes, ${ENERGY_LEVEL_SCALE}`),
    };
    fields.low.setAttribute('aria-label', `Arc ${place + 1} energy low`);
    fields.high.setAttribute('aria-label', `Arc ${place + 1} energy high`);
    const readRow = () => Object.fromEntries(ARC_FIELDS.map(field => [field, fields[field].value]));
    for (const field of ARC_FIELDS) fields[field].onchange = () => onArcEdited(place, readRow());
    const earlier = arcButton(`m3u-arc-earlier-${place}`, 'Earlier', `Move arc ${place + 1} earlier`, () => onArcMoved(place, -1));
    const later = arcButton(`m3u-arc-later-${place}`, 'Later', `Move arc ${place + 1} later`, () => onArcMoved(place, 1));
    const remove = arcButton(`m3u-arc-remove-${place}`, 'Remove', `Remove arc ${place + 1}`, () => onArcRemoved(place));
    const summary = setArcText(document.createElement('summary'), `Arc ${place + 1}`);
    const body = arcElement('div', {className: 'm3u-arc-fields'});
    body.append(...ARC_FIELDS.map(field => arcField(ARC_FIELD_CAPTIONS[field], fields[field])));
    const actions = arcElement('div', {className: 'm3u-arc-actions'});
    actions.append(earlier, later, remove);
    const row = arcElement('details', {id: `m3u-arc-${place}`, className: 'm3u-arc-row'});
    row.append(summary, body, actions);
    return {row, summary, fields, earlier, later, place};
  }

  function showArousalRange(text) {
    if (arousalRange) setArcText(arousalRange, text);
  }

  return Object.freeze({build, show, showArousalRange});
}

function syncRow({summary, fields, earlier, later, place}, arc, unit) {
  if (arc.summary) setArcText(summary, arc.summary);
  for (const field of ARC_FIELDS) {
    if (fields[field].value !== arc[field]) fields[field].value = arc[field];
  }
  fields.length.placeholder = unit;
  fields.length.setAttribute('aria-label', `Arc ${place + 1} length in ${unit}`);
  earlier.disabled = !arc.canMoveEarlier;
  later.disabled = !arc.canMoveLater;
}

function energyLevel(id, title) {
  return arcElement('input', {id, type: 'number', step: '0.1', placeholder: 'default', title});
}

function arcSelect(id, choices, label) {
  const select = arcElement('select', {id});
  select.setAttribute('aria-label', label);
  select.replaceChildren(...choices.map(([value, caption]) => setArcText(arcElement('option', {value}), caption)));
  return select;
}

function arcButton(id, caption, label, onclick) {
  const button = arcElement('button', {id, type: 'button', onclick});
  button.setAttribute('aria-label', label);
  return setArcText(button, caption);
}

function arcField(caption, control) {
  const field = arcElement('div', {className: 'm3u-arc-field'});
  field.append(arcLabel(control, caption), control);
  return field;
}

function arcLabel(control, caption) {
  const label = document.createElement('label');
  label.htmlFor = control.id;
  return setArcText(label, caption);
}

function arcElement(tag, properties) {
  return Object.assign(document.createElement(tag), properties);
}

function setArcText(element, value) {
  element.textContent = value;
  return element;
}
