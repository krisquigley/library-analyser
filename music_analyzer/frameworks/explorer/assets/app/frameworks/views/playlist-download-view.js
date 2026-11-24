// The Download M3U controls in the page (#146), with the energy arc editor (#137):
// renders view models and reports the listener's input. It keeps only the elements it last mounted, to update them in place.
// #234: the controls are the playlist generator's first accordion steps; the page says where Download M3U goes.

import {energyArcEditorView} from './energy-arc-editor-view.js';

const PLAYLIST_CONTROL_IDS = Object.freeze({
  bpmMin: 'm3u-bpm-min', bpmMax: 'm3u-bpm-max', count: 'm3u-count', durationMinutes: 'm3u-duration',
  harmonicMixing: 'm3u-harmonic', minimumKeyStrength: 'm3u-min-key-strength', arcLengthUnit: 'm3u-arc-unit',
  moodHold: 'm3u-mood',
});

export function playlistDownloadView({onControlsEdited, onDownloadRequested, ...arcCommands}) {
  const arcEditor = energyArcEditorView(arcCommands);
  let mounted = null;

  function show(update) {
    if (!mounted) return;
    if (update.values) showControlValues(mounted.controls, update.values);
    disableControl(mounted.controls.minimumKeyStrength, update.minimumKeyStrengthDisabled);
    disableControl(mounted.controls.count, update.lengthDisabled);
    disableControl(mounted.controls.durationMinutes, update.lengthDisabled);
    disableControl(mounted.button, update.downloadDisabled);
    if (update.arcs) arcEditor.show(update.arcs, update.arcLengthPlaceholder);
    if (update.status) showPlaylistStatus(mounted.status, update.status);
    if (update.missing) flagMissingControls(mounted.controls, update.missing);
  }

  function mount(panel, viewModel, finish = panel) {
    const controls = playlistControlElements(viewModel);
    const readControls = () => playlistControlValues(controls);
    for (const control of Object.values(controls)) control.onchange = () => onControlsEdited(readControls());
    for (const control of TYPED_CONTROLS) controls[control].oninput = () => onControlsEdited(readControls());
    for (const control of REQUIRED_CONTROLS) markRequired(controls[control]);
    const button = playlistElement('button', {id: 'download-m3u', type: 'button', disabled: viewModel.downloadDisabled});
    setPlaylistText(button, 'Download M3U');
    button.onclick = () => onDownloadRequested(readControls());
    const status = playlistElement('p', {id: 'm3u-download-status', className: 'muted'});
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    const tempo = playlistStep('playlist-step-tempo', 'Tempo and length');
    tempo.append(playlistField('BPM range (required)', controls.bpmMin, controls.bpmMax),
      playlistField('Length', controls.count, controls.durationMinutes),
      playlistField('Harmonic mixing', controls.harmonicMixing),
      playlistField('Min key strength (0.0–1.0)', controls.minimumKeyStrength));
    const energy = playlistStep('playlist-step-energy', 'Energy plan');
    energy.append(arcEditor.build(controls.arcLengthUnit, viewModel), playlistField('Mood hold', controls.moodHold));
    const steps = playlistElement('div', {id: 'm3u-download-controls', className: 'playlist-steps'});
    steps.append(tempo, energy);
    panel.append(steps);
    finish.append(button, status);
    mounted = {controls, button, status};
  }

  return Object.freeze({mount, show});
}

function playlistControlElements(viewModel) {
  const values = viewModel.values;
  const ids = PLAYLIST_CONTROL_IDS;
  return {
    bpmMin: playlistElement('input', {id: ids.bpmMin, type: 'number', value: values.bpmMin, placeholder: 'min BPM'}),
    bpmMax: playlistElement('input', {id: ids.bpmMax, type: 'number', value: values.bpmMax, placeholder: 'max BPM'}),
    count: playlistElement('input', {id: ids.count, type: 'number', min: '1', max: '1000', value: values.count,
      disabled: viewModel.lengthDisabled}),
    durationMinutes: playlistElement('input', {id: ids.durationMinutes, type: 'number', min: '1', max: '1440',
      value: values.durationMinutes, placeholder: 'minutes (optional)', disabled: viewModel.lengthDisabled,
      title: "Target duration in minutes; replaces the track count when set. Arc lengths replace both."}),
    harmonicMixing: playlistElement('input', {id: ids.harmonicMixing, type: 'checkbox', checked: values.harmonicMixing,
      title: 'Prefer key-compatible transitions and smooth BPM steps'}),
    minimumKeyStrength: playlistElement('input', {id: ids.minimumKeyStrength, type: 'number', min: '0', max: '1',
      step: '0.05', value: values.minimumKeyStrength, disabled: viewModel.minimumKeyStrengthDisabled,
      title: 'Detected keys weaker than this are treated as unknown'}),
    arcLengthUnit: playlistSelect(ids.arcLengthUnit, viewModel.arcLengthUnitChoices, values.arcLengthUnit,
      'Every energy arc length is in this unit'),
    moodHold: playlistSelect(ids.moodHold, viewModel.moodChoices, values.moodHold, 'Prefer tracks stronger in this mood'),
  };
}

function showControlValues(controls, values) {
  for (const [name, control] of Object.entries(controls)) {
    if (name === 'harmonicMixing') control.checked = values.harmonicMixing;
    else control.value = values[name];
  }
}

function playlistControlValues(controls) {
  const values = {};
  for (const [name, control] of Object.entries(controls)) {
    values[name] = name === 'harmonicMixing' ? control.checked : control.value;
  }
  return values;
}

function playlistSelect(id, choices, current, title) {
  const select = playlistElement('select', {id, title});
  select.replaceChildren(...choices.map(([value, label]) => {
    const option = playlistElement('option', {value});
    return setPlaylistText(option, label);
  }));
  select.value = choices.some(([value]) => value === current) ? current : choices[0][0];
  return select;
}

// The controls checked as the listener types (#234), the ones a preview needs, and the gap each one answers for.
const TYPED_CONTROLS = Object.freeze(['bpmMin', 'bpmMax', 'count', 'durationMinutes']);
const REQUIRED_CONTROLS = Object.freeze(['bpmMin', 'bpmMax']);
const CONTROL_GAPS = Object.freeze({bpmMin: 'bpmMin', bpmMax: 'bpmMax', count: 'length', durationMinutes: 'length'});

function markRequired(control) {
  control.required = true;
  control.setAttribute('aria-required', 'true');
}

function flagMissingControls(controls, missing) {
  for (const [control, gap] of Object.entries(CONTROL_GAPS)) {
    controls[control].setAttribute('aria-invalid', String(missing.includes(gap)));
  }
}

function playlistStep(id, title) {
  const step = playlistElement('details', {id, open: true, className: 'playlist-step'});
  step.append(setPlaylistText(document.createElement('summary'), title));
  return step;
}

function playlistField(caption, ...controls) {
  const field = playlistElement('div', {className: 'playlist-field'});
  const label = document.createElement('label');
  label.htmlFor = controls[0].id;
  field.append(setPlaylistText(label, caption), ...controls);
  return field;
}

function playlistElement(tag, properties) {
  return Object.assign(document.createElement(tag), properties);
}

function disableControl(control, disabled) {
  if (disabled !== undefined) control.disabled = disabled;
}

function showPlaylistStatus(status, {text, urgent}) {
  if (!status) return;
  status.setAttribute('role', urgent ? 'alert' : 'status');
  status.setAttribute('aria-live', urgent ? 'assertive' : 'polite');
  setPlaylistText(status, text);
}

function setPlaylistText(element, value) {
  element.textContent = value;
  return element;
}
