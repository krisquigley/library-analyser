// Choosing the current track, undo and reset, and loading its detail (#146).
// Every choice, undo or reset starts a new generation; an answer for an older one is stale and dropped,
// so a slow request can never undo something the listener did later.

import {awaitingServer, nextTrackSelectionState} from '../../domain/track-selection.js';
import {EVENT_BUS} from '../ports/event-bus.js';
import {SELECTIONS} from '../ports/explorer-api.js';
import {requirePort} from '../ports/port.js';
import {SELECTION_TICKETS} from '../ports/selection-tickets.js';
import {TRACK_SELECTION_SESSION} from '../ports/track-selection-session.js';
import {failureOf, trackSelectionEvent} from './track-selection-events.js';

export function createTrackSelection({explorerApi, selectionTickets, selectionSession, eventBus}) {
  requirePort(SELECTIONS, explorerApi);
  requirePort(SELECTION_TICKETS, selectionTickets);
  requirePort(TRACK_SELECTION_SESSION, selectionSession);
  requirePort(EVENT_BUS, eventBus);
  let latestGeneration = 0;
  let latestDetailRequest = 0;
  let detailFlight = null;

  const read = () => selectionSession.read();
  const currentTrackId = () => read().snapshot?.current_track_id ?? null;

  function advance(action, changes = {}) {
    selectionSession.write({...changes, selectionState: nextTrackSelectionState(read().selectionState, action)});
  }

  function publish(type, fields) {
    eventBus.publish(trackSelectionEvent(type, fields));
  }

  function epochOf(snapshot) {
    return typeof snapshot?.selection_epoch === 'number' ? snapshot.selection_epoch : read().epoch;
  }

  function accept(snapshot) {
    advance(snapshot?.current_track_id ? 'accept-track' : 'accept-none', {snapshot, epoch: epochOf(snapshot)});
  }

  function refuse(error) {
    advance('refuse');
    publish('selection-refused', {failure: failureOf(error)});
  }

  async function choose(trackId, {focusCamera = true} = {}) {
    if (typeof trackId !== 'string' || !trackId) throw new TypeError('A track id is required to choose a track');
    const generation = ++latestGeneration;
    const selectionToken = selectionTickets.nextTicket();
    const {snapshot, epoch} = read();
    advance('choose', {snapshot: {...snapshot, current_track_id: trackId}});
    publish('track-chosen', {trackId});
    try {
      const accepted = await explorerApi.chooseCurrentTrack({trackId, selectionToken, selectionEpoch: epoch,
        clientId: selectionTickets.clientId()});
      if (generation !== latestGeneration) return;
      accept(accepted);
      publish('selection-accepted', {trackId: currentTrackId(), focusCamera, rewound: false});
    } catch (error) {
      if (generation !== latestGeneration) return;
      refuse(error);
      return;
    }
    await loadDetail(generation);
  }

  async function rewind(action) {
    const generation = ++latestGeneration;
    advance('rewind');
    publish('selection-rewinding');
    try {
      const accepted = await explorerApi.applyHistory(action);
      if (generation !== latestGeneration) return false;
      accept(accepted);
      publish('selection-accepted', {trackId: currentTrackId(), focusCamera: true, rewound: true});
      return true;
    } catch (error) {
      if (generation !== latestGeneration) return false;
      refuse(error);
      return false;
    }
  }

  function loadDetail(generation) {
    if (generation !== latestGeneration || awaitingServer(read().selectionState)) return Promise.resolve();
    const trackId = currentTrackId();
    if (detailFlight && detailFlight.generation === generation && detailFlight.trackId === trackId) return detailFlight.promise;
    const detailRequest = ++latestDetailRequest;
    if (!trackId) {
      advance('clear');
      publish('no-track-selected');
      return Promise.resolve();
    }
    advance('load-detail');
    publish('track-detail-loading', {trackId});
    const ownsDetail = () => generation === latestGeneration && detailRequest === latestDetailRequest
      && currentTrackId() === trackId;
    const flight = {generation, trackId, promise: null};
    detailFlight = flight;
    flight.promise = (async () => {
      try {
        const detail = await explorerApi.loadTrackDetail(trackId);
        if (!ownsDetail()) return;
        advance('show-detail');
        publish('track-detail-loaded', {trackId, detail});
      } catch (error) {
        if (!ownsDetail()) return;
        advance('fail-detail');
        publish('track-detail-failed', {trackId, failure: failureOf(error)});
      } finally {
        if (detailFlight === flight) detailFlight = null;
      }
    })();
    return flight.promise;
  }

  function retryDetail() {
    if (read().selectionState !== 'detail-failed') return Promise.resolve();
    return loadDetail(latestGeneration);
  }

  function reconcile(snapshot) {
    if (awaitingServer(read().selectionState)) return;
    const trackId = snapshot?.current_track_id ?? null;
    const changed = currentTrackId() !== trackId;
    selectionSession.write({snapshot, epoch: epochOf(snapshot)});
    if (changed) publish('library-selection-changed', {trackId});
  }

  return Object.freeze({
    choose, rewind, loadDetail, retryDetail, reconcile,
    generation: () => latestGeneration,
    awaitingServer: () => awaitingServer(read().selectionState),
  });
}
