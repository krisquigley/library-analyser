// The saved recipe controls in the page (#139): Saved recipes lists them, then a choice of names and Load.

export function savedRecipeView({onListRequested, onLoadRequested}) {
  let mounted = null;

  function mount(panel, viewModel) {
    const list = savedRecipeElement('button', {id: 'saved-recipes-list', type: 'button', textContent: 'Saved recipes',
      title: 'List the recipes saved with music-analyzer playlist-recipe save'});
    const choice = savedRecipeElement('select', {id: 'saved-recipe-choice', hidden: true});
    choice.setAttribute('aria-label', 'Saved recipe');
    const load = savedRecipeElement('button', {id: 'saved-recipe-load', type: 'button', textContent: 'Load', hidden: true});
    const status = savedRecipeElement('p', {id: 'saved-recipe-status', className: 'muted'});
    list.onclick = () => onListRequested();
    load.onclick = () => onLoadRequested(choice.value);
    const section = savedRecipeElement('section', {id: 'saved-recipes'});
    section.append(list, choice, load, status);
    panel.append(section);
    mounted = {list, choice, load, status};
    show(viewModel);
  }

  function show(update) {
    if (!mounted) return;
    if (update.busy !== undefined) mounted.list.disabled = mounted.load.disabled = update.busy;
    if (update.choices) showSavedRecipeChoices(mounted, update.choices);
    if (update.status) showSavedRecipeStatus(mounted.status, update.status);
  }

  return Object.freeze({mount, show});
}

function showSavedRecipeChoices({choice, load}, choices) {
  choice.replaceChildren(...choices.map(({value, label, disabled, title}) =>
    savedRecipeElement('option', {value, textContent: label, disabled, title})));
  choice.value = choices.find(each => !each.disabled)?.value ?? '';
  choice.hidden = load.hidden = !choices.length;
}

function showSavedRecipeStatus(status, {text, urgent}) {
  status.setAttribute('role', urgent ? 'alert' : 'status');
  status.setAttribute('aria-live', urgent ? 'assertive' : 'polite');
  status.textContent = text;
}

function savedRecipeElement(tag, properties) {
  return Object.assign(document.createElement(tag), properties);
}
