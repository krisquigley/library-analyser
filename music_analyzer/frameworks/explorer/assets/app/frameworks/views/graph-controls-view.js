// The mood tracker and the graph filters (#146): renders view models and reports the listener's input.
// It keeps only the elements it last mounted, to update them in place.

export function graphControlsView({onMoodChosen, onBpmRangeEdited, onGenresEdited, onFiltersCleared}) {
  let mounted = null;

  function mount(root) {
    const mood = graphControlElement('select', {id: 'selected-mood'});
    mood.onchange = () => onMoodChosen(mood.value);
    const moodFieldset = graphControlElement('fieldset', {id: 'mood-tracker-controls'});
    moodFieldset.append(setGraphControlText(document.createElement('legend'), 'Selected mood strength'),
      setGraphControlText(document.createElement('label'), 'Mood tracker score label '), mood);
    root.append(moodFieldset);
    const filters = graphFilterElements({onBpmRangeEdited, onGenresEdited, onFiltersCleared});
    root.append(filters.fieldset);
    mounted = {mood, ...filters};
  }

  function showOptions({moodChoices, genreChoices}) {
    if (!mounted) return;
    mounted.mood.replaceChildren(...moodChoices.map(graphControlOption));
    mounted.genres.replaceChildren(...genreChoices.map(graphControlOption));
  }

  function showValues({bpmMin, bpmMax, genres}) {
    if (!mounted) return;
    mounted.bpmMin.value = bpmMin;
    mounted.bpmMax.value = bpmMax;
    for (const option of mounted.genres.options || mounted.genres.children || []) option.selected = genres.includes(option.value);
  }

  function showRejection(message) {
    if (!mounted) return;
    mounted.status.setAttribute('role', 'alert');
    setGraphControlText(mounted.status, message);
  }

  return Object.freeze({mount, showOptions, showValues, showRejection});
}

function graphFilterElements({onBpmRangeEdited, onGenresEdited, onFiltersCleared}) {
  const bpmInput = (id, placeholder, name) => {
    const input = graphControlElement('input', {id, type: 'number', placeholder});
    input.setAttribute('aria-label', name);
    return input;
  };
  const bpmMin = bpmInput('bpm-min', 'min BPM', 'Minimum BPM');
  const bpmMax = bpmInput('bpm-max', 'max BPM', 'Maximum BPM');
  for (const input of [bpmMin, bpmMax]) input.onchange = () => onBpmRangeEdited({bpmMin: bpmMin.value, bpmMax: bpmMax.value});
  const genres = graphControlElement('select', {id: 'genre-filter', multiple: true, size: 4});
  genres.onchange = () => onGenresEdited(Array.from(genres.selectedOptions).map(option => option.value));
  const clear = graphControlElement('button', {id: 'clear-graph-filters', type: 'button'});
  setGraphControlText(clear, 'Clear graph filters');
  clear.onclick = () => onFiltersCleared();
  const status = graphControlElement('p', {id: 'graph-filter-status', className: 'muted'});
  status.setAttribute('aria-live', 'polite');
  const fieldset = graphControlElement('fieldset', {id: 'graph-controls'});
  fieldset.append(setGraphControlText(document.createElement('legend'), 'Graph filters'), bpmMin, bpmMax,
    setGraphControlText(document.createElement('label'), ' Genres ANY '), genres, clear, status);
  return {fieldset, bpmMin, bpmMax, genres, status};
}

function graphControlOption({value, label, selected}) {
  const option = graphControlElement('option', {value});
  setGraphControlText(option, label);
  option.selected = selected;
  return option;
}

function graphControlElement(tag, properties) {
  return Object.assign(document.createElement(tag), properties);
}

function setGraphControlText(element, value) {
  element.textContent = value;
  return element;
}
