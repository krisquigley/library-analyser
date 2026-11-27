// The playlist the listener builds by hand from the graph's labels (#278): track IDs in the order they were added, each
// once. The first + starts it with the selected track and then the neighbour; each later + adds the neighbour, after the
// selected track if the listener reached that one another way. Its length is the server's limit (#277).

export const MOST_HAND_BUILT_TRACKS = 500;
const LONGEST_TRACK_ID = 256;

export const EMPTY_HAND_BUILT_PLAYLIST = Object.freeze([]);

export class HandBuiltPlaylistError extends Error {}

export function addNeighbour(playlist, {selectedTrackId, neighbourId}) {
  const added = [selectedTrackId, neighbourId].filter((trackId, place, both) =>
    !playlist.includes(trackId) && both.indexOf(trackId) === place);
  if (!added.length) return playlist;
  if (playlist.length + added.length > MOST_HAND_BUILT_TRACKS) {
    throw new HandBuiltPlaylistError(`A playlist holds at most ${MOST_HAND_BUILT_TRACKS} tracks`);
  }
  return Object.freeze([...playlist, ...added]);
}

// #292: the listener can choose only a track their playlist holds.
export function trackOfPlaylist(playlist, trackId) {
  if (!playlist.includes(trackId)) throw new HandBuiltPlaylistError('That track is not in your playlist');
  return trackId;
}

// #293: the listener reorders the playlist one place at a time, earlier (-1) or later (1).
export function moveTrack(playlist, trackId, places) {
  if (places !== -1 && places !== 1) throw new HandBuiltPlaylistError('A track moves one place earlier or later');
  const from = playlist.indexOf(trackOfPlaylist(playlist, trackId));
  const to = from + places;
  if (to < 0) throw new HandBuiltPlaylistError('That track is already first');
  if (to >= playlist.length) throw new HandBuiltPlaylistError('That track is already last');
  const moved = [...playlist];
  [moved[from], moved[to]] = [moved[to], moved[from]];
  return Object.freeze(moved);
}

export function removeTrack(playlist, trackId) {
  return Object.freeze(playlist.filter(kept => kept !== trackId));
}

export function handBuiltPlaylistOf(kept) {
  if (kept === null) return EMPTY_HAND_BUILT_PLAYLIST;
  const readable = Array.isArray(kept) && kept.length <= MOST_HAND_BUILT_TRACKS && kept.every(isHandBuiltTrackId)
    && new Set(kept).size === kept.length;
  if (!readable) throw new HandBuiltPlaylistError('The playlist kept in this browser could not be read');
  return Object.freeze([...kept]);
}

function isHandBuiltTrackId(value) {
  return typeof value === 'string' && value.length > 0 && value.length <= LONGEST_TRACK_ID;
}
