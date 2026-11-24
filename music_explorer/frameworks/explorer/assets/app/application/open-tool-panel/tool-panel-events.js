// What happens when the listener opens or closes one of the header's tools (#233).

export const TOOL_PANEL_EVENT_TYPES = Object.freeze(['tool-panel-opened', 'tool-panel-closed']);

export function toolPanelOpened({tool, presentation}) {
  return Object.freeze({type: 'tool-panel-opened', tool, presentation});
}

export function toolPanelClosed(tool) {
  return Object.freeze({type: 'tool-panel-closed', tool});
}
