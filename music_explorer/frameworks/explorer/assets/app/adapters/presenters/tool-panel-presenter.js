// Tool panel events (#233) as what the header and the panels show.

export function toolPanelViewModel(event) {
  return Object.freeze({tool: event.tool, open: event.type === 'tool-panel-opened', modal: event.presentation === 'modal'});
}
