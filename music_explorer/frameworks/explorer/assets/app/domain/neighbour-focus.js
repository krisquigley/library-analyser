// The selected track's neighbourhood in the graph (#243): the track and every track linked to it directly. While a
// shown track is selected, only it, its neighbours and its own links are in focus; everything else is dimmed.

const NO_NEIGHBOUR_FOCUS = Object.freeze({active: false, selectedTrackId: null, neighbourIds: Object.freeze(new Set())});

export function neighbourFocus({trackIds, links}, selectedTrackId) {
  const shown = new Set(trackIds);
  if (!selectedTrackId || !shown.has(selectedTrackId)) return NO_NEIGHBOUR_FOCUS;
  const neighbourIds = new Set();
  for (const {source, target} of links) {
    if (!shown.has(source) || !shown.has(target)) continue;
    if (source === selectedTrackId && target !== selectedTrackId) neighbourIds.add(target);
    if (target === selectedTrackId && source !== selectedTrackId) neighbourIds.add(source);
  }
  return Object.freeze({active: true, selectedTrackId, neighbourIds});
}

export function isFocusedTrack(focus, trackId) {
  return !focus.active || trackId === focus.selectedTrackId || focus.neighbourIds.has(trackId);
}

export function isFocusedLink(focus, {source, target}) {
  return !focus.active || source === focus.selectedTrackId || target === focus.selectedTrackId;
}
