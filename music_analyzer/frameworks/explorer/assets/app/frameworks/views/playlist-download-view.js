// The Download M3U controls in the page (#146): renders view models and reports the listener's input.
// It keeps only the elements it last mounted, to update them in place.

const PLAYLIST_CONTROL_IDS = Object.freeze({
  bpmMin: 'm3u-bpm-min', bpmMax: 'm3u-bpm-max', count: 'm3u-count', durationMinutes: 'm3u-duration',
  harmonicMixing: 'm3u-harmonic', minimumKeyStrength: 'm3u-min-key-strength', energyArc: 'm3u-arc',
  energyLow: 'm3u-energy-low', energyHigh: 'm3u-energy-high', moodHold: 'm3u-mood',
});
const ENERGY_LEVEL_SCALE = '0 is the calmest eligible track, 1 the most energetic';

export function playlistDownloadView({onControlsEdited, onDownloadRequested}) {
  let mounted = null;

  function show(update) {
    if (!mounted) return;
    disableControl(mounted.controls.minimumKeyStrength, update.minimumKeyStrengthDisabled);
    disableControl(mounted.controls.energyLow, update.energyRangeDisabled);
    disableControl(mounted.controls.energyHigh, update.energyRangeDisabled);
    disableControl(mounted.button, update.downloadDisabled);
    if (update.status) showPlaylistStatus(mounted.status, update.status);
  }

  function mount(panel, viewModel) {
    const controls = playlistControlElements(viewModel);
    const readControls = () => playlistControlValues(controls);
    for (const control of Object.values(controls)) control.onchange = () => onControlsEdited(readControls());
    const button = playlistElement('button', {id: 'download-m3u', type: 'button', disabled: viewModel.downloadDisabled});
    setPlaylistText(button, 'Download M3U');
    button.onclick = () => onDownloadRequested(readControls());
    const status = playlistElement('p', {id: 'm3u-download-status', className: 'muted'});
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    const fieldset = playlistElement('fieldset', {id: 'm3u-download-controls'});
    fieldset.append(setPlaylistText(document.createElement('legend'), 'Download M3U'),
      controls.bpmMin, controls.bpmMax, controls.count, controls.durationMinutes,
      controls.harmonicMixing, playlistLabel(controls.harmonicMixing, 'Harmonic mixing'),
      playlistLabel(controls.minimumKeyStrength, 'Min key strength (0.0–1.0)'), controls.minimumKeyStrength,
      controls.energyArc, playlistLabel(controls.energyLow, 'Energy low (0.0–1.0)'), controls.energyLow,
      playlistLabel(controls.energyHigh, 'Energy high (0.0–1.0)'), controls.energyHigh, controls.moodHold,
      button, status);
    panel.append(fieldset);
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
    count: playlistElement('input', {id: ids.count, type: 'number', min: '1', max: '1000', value: values.count}),
    durationMinutes: playlistElement('input', {id: ids.durationMinutes, type: 'number', min: '1', max: '1440',
      value: values.durationMinutes, placeholder: 'minutes (optional)',
      title: 'Target duration in minutes; replaces the track count when set'}),
    harmonicMixing: playlistElement('input', {id: ids.harmonicMixing, type: 'checkbox', checked: values.harmonicMixing,
      title: 'Prefer key-compatible transitions and smooth BPM steps'}),
    minimumKeyStrength: playlistElement('input', {id: ids.minimumKeyStrength, type: 'number', min: '0', max: '1',
      step: '0.05', value: values.minimumKeyStrength, disabled: viewModel.minimumKeyStrengthDisabled,
      title: 'Detected keys weaker than this are treated as unknown'}),
    energyArc: playlistSelect(ids.energyArc, viewModel.arcChoices, values.energyArc,
      'Shape the energy (arousal) of the set over time'),
    energyLow: playlistEnergyLevel(ids.energyLow, values.energyLow, '0.1', `How low the arc goes: ${ENERGY_LEVEL_SCALE}`,
      viewModel.energyRangeDisabled),
    energyHigh: playlistEnergyLevel(ids.energyHigh, values.energyHigh, '0.9', `How high the arc goes: ${ENERGY_LEVEL_SCALE}`,
      viewModel.energyRangeDisabled),
    moodHold: playlistSelect(ids.moodHold, viewModel.moodChoices, values.moodHold, 'Prefer tracks stronger in this mood'),
  };
}

function playlistControlValues(controls) {
  const values = {};
  for (const [name, control] of Object.entries(controls)) {
    values[name] = name === 'harmonicMixing' ? control.checked : control.value;
  }
  return values;
}

function playlistEnergyLevel(id, value, placeholder, title, disabled) {
  return playlistElement('input', {id, type: 'number', min: '0', max: '1', step: '0.05', value, placeholder, title, disabled});
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

function playlistLabel(control, caption) {
  const label = document.createElement('label');
  label.htmlFor = control.id;
  return setPlaylistText(label, caption);
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
