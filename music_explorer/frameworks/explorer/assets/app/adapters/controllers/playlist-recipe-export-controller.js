// The Export recipe button's command (#139): export the drafted playlist from the current track.

export function playlistRecipeExportController({playlistRecipeExport, currentTrackId}) {
  return Object.freeze({
    exportRequested: () => playlistRecipeExport.exportRecipe(currentTrackId()),
  });
}
