// Loading the library graph, choosing the mood it tracks and filtering what it shows (#146).

import {applyMoodGraphFilters, clearedGraphFilters, editGraphControls} from '../../domain/graph-filters.js';
import {nextGraphLoadState} from '../../domain/graph-load.js';
import {moodToTrack} from '../../domain/mood-graph.js';
import {FRAMES} from '../ports/clock.js';
import {EVENT_BUS} from '../ports/event-bus.js';
import {MOOD_GRAPHS} from '../ports/explorer-api.js';
import {GRAPH_SESSION} from '../ports/graph-session.js';
import {requirePort} from '../ports/port.js';
import {
  graphControlsEdited, graphFiltersApplied, graphLoadFailed, graphLoadStarted, graphModelBuilding, graphModelBuilt, graphReady,
  graphRenderDue,
} from './graph-load-events.js';

// buildGraphModel turns the server's graph response into the domain model. It is passed in, not
// imported, while the browser diagnostic still times that step by wrapping the page's builder.
export function createGraphLoad({explorerApi, graphSession, clock, eventBus, buildGraphModel}) {
  requirePort(MOOD_GRAPHS, explorerApi);
  requirePort(GRAPH_SESSION, graphSession);
  requirePort(FRAMES, clock);
  requirePort(EVENT_BUS, eventBus);
  if (typeof buildGraphModel !== 'function') throw new TypeError('A graph load needs a graph model builder');
  let latestLoad = 0;

  function advance(action, changes = {}) {
    graphSession.write({...changes, loadState: nextGraphLoadState(graphSession.read().loadState, action)});
  }

  function replaceControls(controls) {
    graphSession.write({controls});
    eventBus.publish(graphControlsEdited(controls));
  }

  function editControls(changes) {
    replaceControls(editGraphControls(graphSession.read().controls, changes));
  }

  async function buildAndRender(load) {
    const response = await explorerApi.loadMoodGraph(graphSession.read().controls.mood);
    if (load !== latestLoad) return;
    eventBus.publish(graphModelBuilding());
    const model = buildGraphModel(response);
    const requested = graphSession.read().controls;
    const controls = editGraphControls(requested, {mood: moodToTrack(requested.mood, model)});
    const visible = applyMoodGraphFilters(model, controls);
    advance('build', {model, visible, controls});
    eventBus.publish(graphModelBuilt({model, visible, controls}));
    await clock.nextFrame();
    if (load !== latestLoad) return;
    eventBus.publish(graphRenderDue(visible));
    advance('render');
    eventBus.publish(graphReady({model, visible}));
  }

  async function load() {
    const thisLoad = ++latestLoad;
    advance('start');
    eventBus.publish(graphLoadStarted());
    try {
      await buildAndRender(thisLoad);
    } catch (error) {
      if (thisLoad !== latestLoad) return;
      advance('fail');
      eventBus.publish(graphLoadFailed(error?.message || String(error)));
      throw error;
    }
  }

  function applyFilters() {
    const {loadState, model, controls, visible: shownBefore} = graphSession.read();
    if (loadState !== 'ready') {
      eventBus.publish(graphFiltersApplied({shown: false, model, visible: shownBefore}));
      return false;
    }
    const visible = applyMoodGraphFilters(model, controls);
    graphSession.write({visible});
    eventBus.publish(graphFiltersApplied({shown: true, model, visible}));
    return true;
  }

  return Object.freeze({
    load,
    editControls,
    applyFilters,
    async chooseMood(mood) {
      editControls({mood});
      if (graphSession.read().loadState === 'ready') await load();
    },
    clearFilters() {
      replaceControls(clearedGraphFilters(graphSession.read().controls));
      return applyFilters();
    },
  });
}
