// What the track list shows for a search (#146): one row per track, the title over the artist with a BPM badge when
// the loaded graph knows it (#235, owner decision A), and a tone for each state: waiting, searching, results,
// nothing found or failed.

const SEARCHING_STATES = Object.freeze(['debouncing', 'loading']);
const EMPTY_MESSAGES = Object.freeze({idle: 'Search for tracks to begin', ready: 'No tracks match your search'});

export function trackListViewModel({tracks, results, searchState, failure, currentTrackId, trackBpms = new Map()}) {
  const total = results.metadata.track_count ?? null;
  const counted = total == null ? `${tracks.length} tracks` : `${tracks.length} of ${total} tracks`;
  const busy = searchState === 'loading';
  return {
    caption: counted,
    rows: tracks.map(track => ({trackId: track.handle, title: trackTitle(track), artist: track.artist || 'Unknown artist',
      bpmBadge: bpmBadge(trackBpms.get(track.handle)), current: track.handle === currentTrackId})),
    emptyMessage: EMPTY_MESSAGES[searchState] || '',
    emptyHidden: tracks.length !== 0 || !Object.hasOwn(EMPTY_MESSAGES, searchState),
    status: trackListStatus({searchState, failure, tracks, counted}),
    tone: trackListTone(searchState, tracks),
    busy,
    loadMore: results.nextCursor ? {disabled: busy} : null,
    retry: failure != null,
  };
}

// Once the graph knows the BPMs, the rows already shown get their badges in place (#235).
export function trackBpmBadges(tracks, trackBpms) {
  return tracks.map(track => ({trackId: track.handle, bpmBadge: bpmBadge(trackBpms.get(track.handle))}));
}

function trackTitle(track) {
  return track.title || track.display_label || track.handle;
}

function bpmBadge(bpm) {
  return typeof bpm === 'number' && Number.isFinite(bpm) ? `${Math.round(bpm)} BPM` : null;
}

function trackListStatus({searchState, failure, tracks, counted}) {
  if (SEARCHING_STATES.includes(searchState)) return 'Searching tracks…';
  if (searchState === 'failed') return `Search failed: ${failure.message}`;
  return searchState === 'idle' && !tracks.length ? '' : counted;
}

function trackListTone(searchState, tracks) {
  if (SEARCHING_STATES.includes(searchState)) return 'searching';
  if (searchState === 'failed') return 'failed';
  if (searchState === 'idle' && !tracks.length) return 'idle';
  return tracks.length ? 'results' : 'empty';
}
