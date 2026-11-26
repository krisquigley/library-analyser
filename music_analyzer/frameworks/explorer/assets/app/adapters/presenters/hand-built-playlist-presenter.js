// What the strip over the graph shows of the hand-built playlist (#278): its tracks in order, each removable, and how
// its download is going. A track not yet labelled is named by its place.

import {trackLabelText} from './track-label-presenter.js';

const DOWNLOAD_STATUSES = Object.freeze({
  'hand-built-playlist-download-started': () => ({text: 'Preparing the M3U…', urgent: false}),
  'hand-built-playlist-downloaded': () => ({text: 'M3U downloaded', urgent: false}),
  'hand-built-playlist-download-failed': event => ({text: `Could not download the playlist: ${event.message}`, urgent: true}),
});

export function handBuiltPlaylistViewModel({trackIds, labels, notice}) {
  const named = new Map(labels.map(label => [label.trackId, trackLabelText(label)]));
  const empty = trackIds.length === 0;
  return {
    hidden: empty && !notice,
    heading: `Your playlist · ${trackIds.length} ${trackIds.length === 1 ? 'track' : 'tracks'}`,
    downloadDisabled: empty, clearDisabled: empty,
    rows: trackIds.map((trackId, index) => {
      const place = index + 1;
      const name = named.get(trackId);
      return {trackId, text: `${place}. ${name || `Track ${place}`}`,
        removeLabel: `Remove ${name || `track ${place}`} from your playlist`};
    }),
    notice: {text: notice, urgent: Boolean(notice)},
  };
}

export function presentHandBuiltPlaylistDownload(event) {
  return DOWNLOAD_STATUSES[event.type](event);
}
