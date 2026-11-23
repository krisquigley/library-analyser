// What happens when a listener exports the drafted playlist as a recipe file (#139).

export const PLAYLIST_RECIPE_EXPORT_EVENT_TYPES = Object.freeze(['playlist-recipe-exported', 'playlist-recipe-export-failed']);

export function playlistRecipeExported(filename) {
  return Object.freeze({type: 'playlist-recipe-exported', filename});
}

export function playlistRecipeExportFailed(message) {
  return Object.freeze({type: 'playlist-recipe-export-failed', message});
}
