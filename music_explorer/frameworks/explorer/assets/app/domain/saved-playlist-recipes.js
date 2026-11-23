// The lifecycle of the saved recipe list and of loading one recipe into the draft (#139), as a transitions table.

const SAVED_RECIPE_TRANSITIONS = Object.freeze({
  idle: Object.freeze({list: 'listing'}),
  listing: Object.freeze({succeed: 'listed', fail: 'failed'}),
  listed: Object.freeze({list: 'listing', load: 'loading'}),
  loading: Object.freeze({succeed: 'loaded', fail: 'failed'}),
  loaded: Object.freeze({list: 'listing', load: 'loading'}),
  failed: Object.freeze({list: 'listing', load: 'loading'}),
});

export const SAVED_RECIPE_STATES = Object.freeze(Object.keys(SAVED_RECIPE_TRANSITIONS));

export class SavedRecipeTransitionError extends Error {}

export function nextSavedRecipeState(state, action) {
  const next = Object.hasOwn(SAVED_RECIPE_TRANSITIONS, state) && SAVED_RECIPE_TRANSITIONS[state][action];
  if (!next) throw new SavedRecipeTransitionError(`Saved recipes cannot ${action} while ${state}`);
  return next;
}
