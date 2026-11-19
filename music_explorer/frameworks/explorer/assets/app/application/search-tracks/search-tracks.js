// Searching the library's tracks a page at a time, as the listener types (#146).

import {emptyTrackResults, nextTrackSearchState, trackResultsWithPage} from '../../domain/track-search.js';
import {DELAYS} from '../ports/clock.js';
import {EVENT_BUS} from '../ports/event-bus.js';
import {TRACK_SEARCHES} from '../ports/explorer-api.js';
import {requirePort} from '../ports/port.js';
import {TRACK_SEARCH_SESSION} from '../ports/track-search-session.js';
import {trackSearchEvent} from './track-search-events.js';

const TYPING_PAUSE_MS = 150;

export function createTrackSearch({explorerApi, trackSession, clock, eventBus}) {
  requirePort(TRACK_SEARCHES, explorerApi);
  requirePort(TRACK_SEARCH_SESSION, trackSession);
  requirePort(DELAYS, clock);
  requirePort(EVENT_BUS, eventBus);
  let latestSearch = 0;

  function advance(type, action, changes = {}) {
    trackSession.write({...changes, searchState: nextTrackSearchState(trackSession.read().searchState, action)});
    eventBus.publish(trackSearchEvent(type, trackSession.read()));
  }

  async function loadPage({query, cursor = null, append = false}) {
    const trimmed = String(query || '').trim();
    if (!trimmed || trackSession.read().searchState === 'loading') return;
    const thisSearch = ++latestSearch;
    advance('track-search-started', 'fetch', {failure: null});
    try {
      const page = await explorerApi.searchTracks({query: trimmed, cursor});
      if (thisSearch !== latestSearch) return;
      const base = append ? trackSession.read().results : emptyTrackResults(trimmed);
      advance('track-page-loaded', 'succeed', {results: trackResultsWithPage(base, page, {append})});
    } catch (error) {
      if (thisSearch !== latestSearch) return;
      const failure = Object.freeze({message: error?.message || String(error), query: trimmed, cursor, append});
      advance('track-search-failed', 'fail', {failure});
    }
  }

  return Object.freeze({
    loadPage,
    async queryTyped(query) {
      const trimmed = String(query || '').trim();
      const thisSearch = ++latestSearch;
      advance('track-search-edited', trimmed ? 'type' : 'clear', {results: emptyTrackResults(trimmed), failure: null});
      if (!trimmed) return;
      await clock.wait(TYPING_PAUSE_MS);
      if (thisSearch === latestSearch) await loadPage({query: trimmed});
    },
    loadMore() {
      const {results} = trackSession.read();
      return results.nextCursor ? loadPage({query: results.query, cursor: results.nextCursor, append: true}) : Promise.resolve();
    },
    retry() {
      const {failure} = trackSession.read();
      return failure ? loadPage(failure) : Promise.resolve();
    },
  });
}
