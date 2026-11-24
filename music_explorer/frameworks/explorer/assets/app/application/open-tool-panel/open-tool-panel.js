// Opening and closing the header's tools over the graph (#233). Opening a modal closes any other open modal first.

import {TOOL_PANELS, ToolPanelTransitionError, isToolPanel, modalsDisplacedBy, nextToolPanelState} from '../../domain/tool-panels.js';
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
    for (const displaced of modalsDisplacedBy(tool, openTools())) close(displaced);
    states.set(tool, next);
    eventBus.publish(toolPanelOpened({tool, presentation: TOOL_PANELS[tool]}));
  }

  function toggle(tool) {
    if (isOpen(tool)) close(tool);
    else open(tool);
  }

  return Object.freeze({toggle, close, isOpen});
}
