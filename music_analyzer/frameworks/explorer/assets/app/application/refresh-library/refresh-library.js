// Refreshing the library view (#146): let the loading screen paint, read the library state the server holds,
// reconcile the listener's selection with it, and load the current track's detail.
// A newer refresh supersedes an older one, which then stops silently; a refresh yields to a newer selection.

import {nextLibraryRefreshState} from '../../domain/library-refresh.js';
import {FRAMES} from '../ports/clock.js';
import {EVENT_BUS} from '../ports/event-bus.js';
import {LIBRARY_STATES} from '../ports/explorer-api.js';
import {LIBRARY_SELECTION} from '../ports/library-selection.js';
import {requirePort} from '../ports/port.js';
import {libraryRefreshEvent} from './library-refresh-events.js';

export function createLibraryRefresh({explorerApi, librarySelection, clock, eventBus}) {
  requirePort(LIBRARY_STATES, explorerApi);
  requirePort(LIBRARY_SELECTION, librarySelection);
  requirePort(FRAMES, clock);
  requirePort(EVENT_BUS, eventBus);
  let refreshState = 'idle';
  let latestRefresh = 0;

  function advance(type, action, fields = {}) {
    refreshState = nextLibraryRefreshState(refreshState, action);
    eventBus.publish(libraryRefreshEvent(type, {refreshState, ...fields}));
  }

  async function refresh() {
    const thisRefresh = ++latestRefresh;
    const selection = librarySelection.generation();
    // A refresh begun during a selection or history request cannot reconcile its older snapshot.
    const selectionPending = librarySelection.awaitingServer();
    const stopped = () => {
      if (thisRefresh !== latestRefresh) return true;
      if (selection === librarySelection.generation()) return false;
      advance('library-refresh-yielded', 'yield');
      return true;
    };
    try {
      advance('library-refresh-started', 'begin');
      await clock.nextFrame();
      if (stopped()) return;
      advance('library-state-loading', 'read');
      const snapshot = await explorerApi.loadLibraryState();
      if (stopped()) return;
      if (!selectionPending) librarySelection.reconcile(snapshot);
      if (stopped()) return;
      if (!selectionPending) await librarySelection.loadDetail(selection);
      if (stopped()) return;
      advance('library-loaded', 'finish');
    } catch (error) {
      if (stopped()) return;
      advance('library-refresh-failed', 'fail', {message: failureMessage(error)});
      throw error;
    }
  }

  return Object.freeze({refresh, refreshState: () => refreshState});
}

function failureMessage(error) {
  return String((error && error.message) || error || 'Loading failed');
}
