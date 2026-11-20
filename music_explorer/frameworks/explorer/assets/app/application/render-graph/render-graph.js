// Drawing the graph on demand (#86, #146). Each page frame reports the view's pose and, while drawing, that a
// frame was drawn; a quiet view pauses the drawing. A moved view resumes it inside that frame. Any other wake
// (input, new data, a selection, a resize) resumes it at the start of the next frame, so the handler that woke
// it is not delayed by a synchronous redraw.

import {nextGraphRenderingState, quietLongEnough} from '../../domain/graph-rendering.js';
import {EVENT_BUS} from '../ports/event-bus.js';
import {GRAPH_RENDERER} from '../ports/graph-renderer.js';
import {requirePort} from '../ports/port.js';
import {graphRenderingEvent} from './render-graph-events.js';

export function createGraphRendering({renderer, eventBus}) {
  requirePort(GRAPH_RENDERER, renderer);
  requirePort(EVENT_BUS, eventBus);
  let state = 'drawing';
  let quietSince = null;
  let viewPose = null;
  let resumeAtNextFrame = false;

  function transition(action, eventType) {
    state = nextGraphRenderingState(state, action);
    eventBus.publish(graphRenderingEvent(eventType));
  }

  function resumeDrawing() {
    quietSince = null;
    if (state !== 'paused') return false;
    transition('wake', 'graph-rendering-resumed');
    return true;
  }

  function wake() {
    if (resumeDrawing()) resumeAtNextFrame = true;
  }

  function viewObserved(pose) {
    const moved = pose !== viewPose;
    viewPose = pose;
    if ((moved && resumeDrawing()) || resumeAtNextFrame) {
      resumeAtNextFrame = false;
      renderer.resume();
    }
  }

  function frameDrawn(now) {
    if (state !== 'drawing') return;
    if (quietSince === null) {
      quietSince = now;
      return;
    }
    if (!quietLongEnough(quietSince, now) || !renderer.canPause()) return;
    renderer.pause();
    transition('pause', 'graph-rendering-paused');
  }

  return Object.freeze({wake, viewObserved, frameDrawn, drawing: () => state === 'drawing'});
}
