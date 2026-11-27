// What the strip over the graph shows of the hand-built playlist (#278): its tracks in order, each removable, and how
// its download is going. #287: the tracks are a table like the playlist preview's, read from the playlist's last
// preview, which may be of an earlier list: a track it has not seen waits, one it left out is no longer playable, and
// a step is shown only when the preview took that same step.

import {previewTrackRow, previewedLength} from './playlist-preview-presenter.js';

const NOT_PREVIEWED = '…';
const LEFT_OUT_BLANK = '—';
const NO_LONGER_PLAYABLE = 'No longer playable from the library';

const DOWNLOAD_STATUSES = Object.freeze({
  'hand-built-playlist-download-started': () => ({text: 'Preparing the M3U…', urgent: false}),
  'hand-built-playlist-downloaded': () => ({text: 'M3U downloaded', urgent: false}),
  'hand-built-playlist-download-failed': event => ({text: `Could not download the playlist: ${event.message}`, urgent: true}),
});

export function handBuiltPlaylistViewModel({trackIds, notice, previewed}) {
  const tracks = new Map((previewed?.tracks || []).map(track => [track.trackId, track]));
  const asked = new Set(previewed?.trackIds || []);
  const steps = new Map((previewed?.transitions || []).map(step => [stepKey(step.fromTrackId, step.toTrackId), step]));
  const empty = trackIds.length === 0;
  return {
    hidden: empty && !notice,
    heading: stripHeading(trackIds, tracks),
    downloadDisabled: empty, clearDisabled: empty,
    rows: trackIds.map((trackId, place) => movableRow(tracks.has(trackId)
      ? playableRow(tracks.get(trackId), place, steps.get(stepKey(trackIds[place - 1], trackId)))
      : unseenRow(trackId, place, asked.has(trackId) ? LEFT_OUT_BLANK : NOT_PREVIEWED), place, trackIds.length)),
    notice: {text: notice, urgent: Boolean(notice)},
  };
}

export function presentHandBuiltPlaylistDownload(event) {
  return DOWNLOAD_STATUSES[event.type](event);
}

function stripHeading(trackIds, tracks) {
  const count = `Your playlist · ${trackIds.length} ${trackIds.length === 1 ? 'track' : 'tracks'}`;
  const known = trackIds.filter(trackId => tracks.has(trackId)).map(trackId => tracks.get(trackId));
  const length = previewedLength(known);
  return known.length && length !== 'length unknown' ? `${count} · ${length}` : count;
}

function playableRow(track, place, step) {
  const {target: _arcTarget, ...row} = previewTrackRow(track, place, step);
  return {...row, playable: true, removeLabel: `Remove ${row.track} from your playlist`, name: row.track};
}

// #293: each row can move a place earlier or later, except past either end.
function movableRow({name, ...row}, place, count) {
  return {...row, earlierLabel: `Move ${name} earlier`, laterLabel: `Move ${name} later`, first: place === 0,
    last: place === count - 1};
}

// A track the last preview has not seen, or one it left out because the library can no longer play it.
function unseenRow(trackId, place, blank) {
  const leftOut = blank === LEFT_OUT_BLANK;
  return {trackId, place: String(place + 1), track: leftOut ? NO_LONGER_PLAYABLE : `Track ${place + 1}`,
    length: blank, bpm: blank, key: blank, energy: blank, transition: blank, playable: !leftOut,
    removeLabel: `Remove track ${place + 1} from your playlist`, name: `track ${place + 1}`};
}

function stepKey(fromTrackId, toTrackId) {
  return `${fromTrackId}\u0000${toTrackId}`;
}
