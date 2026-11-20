// The Download M3U controls' input (#146), with its energy arc editor (#137):
// validated, then handed to the download-playlist use case.

import {ENERGY_ARC_EDIT, PLAYLIST_DRAFT_EDIT} from '../../application/download-playlist/playlist-draft-edit-schema.js';
import {RequestSchemaError, validRequest} from './request-schema.js';

export function playlistDownloadController({playlistDownload, currentTrackId, rejectInput}) {
  function accepted(schema, request) {
    try {
      return validRequest(schema, request);
    } catch (error) {
      if (!(error instanceof RequestSchemaError)) throw error;
      rejectInput(error.message);
      return null;
    }
  }

  function controlsEdited(controls) {
    const edit = accepted(PLAYLIST_DRAFT_EDIT, controls);
    if (edit) playlistDownload.edit(edit);
    return edit !== null;
  }

  return Object.freeze({
    controlsEdited,
    arcAdded: () => playlistDownload.addArc(),
    arcRemoved: place => playlistDownload.removeArc(place),
    arcMoved: (place, offset) => playlistDownload.moveArc(place, offset),
    arcEdited(place, fields) {
      const edit = accepted(ENERGY_ARC_EDIT, fields);
      if (edit) playlistDownload.editArc(place, edit);
    },
    async downloadRequested(controls) {
      if (controlsEdited(controls)) await playlistDownload.download(currentTrackId());
    },
  });
}
