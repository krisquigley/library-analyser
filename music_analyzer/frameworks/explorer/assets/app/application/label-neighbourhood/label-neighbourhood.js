// Labelling a selected track and its nearest neighbours with their titles and artists (#243). The page asks once per
// neighbourhood; an answer for an earlier one is ignored once another has been asked for.

import {labelledTrackIds, nextNeighbourhoodLabelState} from '../../domain/neighbourhood-labels.js';
import {EVENT_BUS} from '../ports/event-bus.js';
import {TRACK_LABELS} from '../ports/explorer-api.js';
import {requirePort} from '../ports/port.js';
import {neighbourhoodLabelled, neighbourhoodLabelling, neighbourhoodLabelsCleared, neighbourhoodLabelsFailed}
  from './neighbourhood-label-events.js';

export function createNeighbourhoodLabels({explorerApi, eventBus}) {
  requirePort(TRACK_LABELS, explorerApi);
  requirePort(EVENT_BUS, eventBus);
  let state = 'unlabelled';
  let asked = '';

  function move(action, event) {
    state = nextNeighbourhoodLabelState(state, action);
    eventBus.publish(event);
  }

  async function label(focus) {
    const trackIds = labelledTrackIds(focus);
    const neighbourhood = trackIds.join('\n');
    if (neighbourhood === asked) return;
    asked = neighbourhood;
    if (!trackIds.length) return move('clear', neighbourhoodLabelsCleared());
    move('request', neighbourhoodLabelling(trackIds));
    try {
      const labels = await explorerApi.labelTracks(trackIds);
      if (asked === neighbourhood) move('succeed', neighbourhoodLabelled({selectedTrackId: focus.selectedTrackId, labels}));
    } catch (error) {
      if (asked === neighbourhood) move('fail', neighbourhoodLabelsFailed(error?.message || String(error)));
    }
  }

  return Object.freeze({label, state: () => state});
}
