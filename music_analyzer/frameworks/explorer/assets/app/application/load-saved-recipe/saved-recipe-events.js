// What happens while a listener lists the saved recipes and loads one into the draft (#139).

export const SAVED_RECIPE_EVENT_TYPES = Object.freeze(['saved-recipes-listing', 'saved-recipes-listed', 'saved-recipe-loading',
  'saved-recipe-loaded', 'saved-recipe-failed']);

export function savedRecipesListing() {
  return Object.freeze({type: 'saved-recipes-listing'});
}

export function savedRecipesListed(recipes) {
  return Object.freeze({type: 'saved-recipes-listed', recipes});
}

export function savedRecipeLoading(name) {
  return Object.freeze({type: 'saved-recipe-loading', name});
}

export function savedRecipeLoaded({name, startTrackId, draft}) {
  return Object.freeze({type: 'saved-recipe-loaded', name, startTrackId, draft});
}

export function savedRecipeFailed(message) {
  return Object.freeze({type: 'saved-recipe-failed', message});
}
