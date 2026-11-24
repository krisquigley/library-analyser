// The header's tool buttons and the panels' close controls (#233). The tool is checked before the use case sees it,
// and a close request for a panel the page has already closed is ignored.

import {isToolPanel} from '../../domain/tool-panels.js';

export function toolPanelController({toolPanels, rejectInput}) {
  function checked(tool, command) {
    if (!isToolPanel(tool)) return rejectInput(`There is no tool called ${tool}`);
    return command(tool);
  }

  return Object.freeze({
    toggleRequested: tool => checked(tool, toolPanels.toggle),
    openRequested: tool => checked(tool, toolPanels.open),
    closeRequested: tool => checked(tool, known => (toolPanels.isOpen(known) ? toolPanels.close(known) : undefined)),
  });
}
