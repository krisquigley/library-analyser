// Opening and closing the header's tools over the graph (#233). Opening a panel first closes the open one of its kind.

import {TOOL_PANELS, ToolPanelTransitionError, isToolPanel, panelsDisplacedBy, nextToolPanelState} from '../../domain/tool-panels.js';
import {EVENT_BUS} from '../ports/event-bus.js';
import {requirePort} from '../ports/port.js';
import {toolPanelClosed, toolPanelOpened} from './tool-panel-events.js';

export function createToolPanels({eventBus}) {
  requirePort(EVENT_BUS, eventBus);
  const states = new Map(Object.keys(TOOL_PANELS).map(tool => [tool, 'closed']));

  function known(tool) {
    if (!isToolPanel(tool)) throw new ToolPanelTransitionError(`There is no tool panel called ${tool}`);
    return tool;
  }

  function isOpen(tool) {
    return states.get(known(tool)) === 'open';
  }

  function openTools() {
    return [...states].filter(([, state]) => state === 'open').map(([tool]) => tool);
  }

  function close(tool) {
    states.set(tool, nextToolPanelState(states.get(known(tool)), 'close'));
    eventBus.publish(toolPanelClosed(tool));
  }

  function open(tool) {
    const next = nextToolPanelState(states.get(tool), 'open');
    for (const displaced of panelsDisplacedBy(tool, openTools())) close(displaced);
    states.set(tool, next);
    eventBus.publish(toolPanelOpened({tool, presentation: TOOL_PANELS[tool]}));
  }

  function toggle(tool) {
    if (isOpen(tool)) close(tool);
    else open(tool);
  }

  // A shortcut to a panel (#236): opens it unless it is already open.
  function openPanel(tool) {
    if (!isOpen(tool)) open(tool);
  }

  return Object.freeze({toggle, open: openPanel, close, isOpen});
}
