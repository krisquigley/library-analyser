// What the track list shows for a search (#146).

const SEARCHING_STATES = Object.freeze(['debouncing', 'loading']);
const EMPTY_MESSAGES = Object.freeze({idle: 'Search for tracks to begin', ready: 'No tracks match your search'});

export function trackListViewModel({tracks, results, searchState, failure, currentTrackId}) {
  const total = results.metadata.track_count ?? null;
  const counted = total == null ? `${tracks.length} tracks` : `Showing ${tracks.length} of ${total}`;
  const busy = searchState === 'loading';
  return {
    caption: counted,
    rows: tracks.map(track => ({trackId: track.handle, title: trackTitle(track), artist: track.artist || 'Unknown artist',
      current: track.handle === currentTrackId})),
    emptyMessage: EMPTY_MESSAGES[searchState] || '',
    emptyHidden: tracks.length !== 0 || !Object.hasOwn(EMPTY_MESSAGES, searchState),
    status: trackListStatus({searchState, failure, tracks, total}),
    busy,
    loadMore: results.nextCursor ? {disabled: busy} : null,
    retry: failure != null,
  };
}

function trackTitle(track) {
  return track.title || track.display_label || track.handle;
}

function trackListStatus({searchState, failure, tracks, total}) {
  if (SEARCHING_STATES.includes(searchState)) return 'Searching tracks…';
  if (searchState === 'failed') return `Search failed: ${failure.message}`;
  return total == null ? `${tracks.length} tracks loaded` : `Showing ${tracks.length} of ${total}`;
}
