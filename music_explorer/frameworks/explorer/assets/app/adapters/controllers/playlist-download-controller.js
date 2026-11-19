// The Download M3U controls' input (#146): validated, then handed to the download-playlist use case.

import {PLAYLIST_DRAFT_EDIT} from '../../application/download-playlist/playlist-draft-edit-schema.js';
import {RequestSchemaError, validRequest} from './request-schema.js';

export function playlistDownloadController({playlistDownload, currentTrackId, rejectInput}) {
  function controlsEdited(controls) {
    try {
      playlistDownload.edit(validRequest(PLAYLIST_DRAFT_EDIT, controls));
      return true;
    } catch (error) {
      if (!(error instanceof RequestSchemaError)) throw error;
      rejectInput(error.message);
      return false;
    }
  }

  return Object.freeze({
    controlsEdited,
    async downloadRequested(controls) {
      if (controlsEdited(controls)) await playlistDownload.download(currentTrackId());
    },
  });
}
