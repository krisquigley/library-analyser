// The Preview button's command (#138): preview the drafted playlist from the current track.

export function playlistPreviewController({playlistPreview, currentTrackId}) {
  return Object.freeze({
    previewRequested: () => playlistPreview.preview(currentTrackId()),
  });
}
