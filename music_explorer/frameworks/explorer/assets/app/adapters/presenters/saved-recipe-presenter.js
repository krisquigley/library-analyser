// What the saved recipe controls show for each event (#139).

const SAVED_RECIPE_EVENT_VIEWS = Object.freeze({
  'saved-recipes-listing': () => ({busy: true, status: {text: 'Reading saved recipes…', urgent: false}}),
  'saved-recipes-listed': event => ({busy: false, status: {text: listedText(event.recipes.length), urgent: false},
    choices: event.recipes.map(recipeChoice)}),
  'saved-recipe-loading': event => ({busy: true, status: {text: `Loading ${event.name}…`, urgent: false}}),
  'saved-recipe-loaded': event => ({busy: false, status: {text: `Loaded ${event.name}.`, urgent: false}}),
  'saved-recipe-failed': event => ({busy: false, status: {text: `Saved recipe failed: ${event.message}`, urgent: true}}),
});

export function savedRecipesViewModel() {
  return {busy: false, choices: null, status: {text: '', urgent: false}};
}

export function presentSavedRecipeEvent(event) {
  return SAVED_RECIPE_EVENT_VIEWS[event.type](event);
}

export function presentRejectedSavedRecipeInput(message) {
  return {status: {text: message, urgent: true}};
}

function listedText(count) {
  if (!count) return 'No saved recipes. Export one and save it with music-analyzer playlist-recipe save.';
  return count === 1 ? '1 saved recipe.' : `${count} saved recipes.`;
}

function recipeChoice({name, updatedAt, problem}) {
  return problem
    ? {value: name, label: `${name} (cannot load)`, disabled: true, title: problem}
    : {value: name, label: `${name} (saved ${updatedAt.slice(0, 10)})`, disabled: false, title: ''};
}
