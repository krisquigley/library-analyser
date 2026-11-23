// What the listener is told after exporting the drafted playlist as a recipe file (#139).

const EXPORT_EVENT_VIEWS = Object.freeze({
  'playlist-recipe-exported': event => ({status: {urgent: false, text: `Recipe exported as ${event.filename}. `
    + `Save it with: music-analyzer playlist-recipe save --name NAME --file ${event.filename}`}}),
  'playlist-recipe-export-failed': event => ({status: {text: `Recipe export failed: ${event.message}`, urgent: true}}),
});

export function presentPlaylistRecipeExportEvent(event) {
  return EXPORT_EVENT_VIEWS[event.type](event);
}
