// The header's tool buttons and the tool panels over the graph (#233). Each tool has a header button
// (open-<tool>), a <dialog> (<tool>-panel) and optionally a close button (close-<tool>). Esc, the close button and
// a click on a modal's backdrop only ask to close: the panel closes when the use case says so.

import {TOOL_PANELS} from '../../domain/tool-panels.js';

// Buttons elsewhere on the page that open a tool without toggling it (#236).
const TOOL_SHORTCUTS = Object.freeze({'detail-write-tags': 'tag-write'});

export function toolPanelsView({onToggleRequested, onCloseRequested, onOpenRequested}) {
  function mount() {
    for (const [id, tool] of Object.entries(TOOL_SHORTCUTS)) {
      const shortcut = document.getElementById(id);
      if (shortcut) shortcut.onclick = () => onOpenRequested(tool);
    }
    for (const tool of Object.keys(TOOL_PANELS)) {
      const opener = document.getElementById(`open-${tool}`);
      if (opener) {
        opener.setAttribute('aria-expanded', 'false');
        opener.onclick = () => onToggleRequested(tool);
      }
      const closer = document.getElementById(`close-${tool}`);
      if (closer) closer.onclick = () => onCloseRequested(tool);
      const panel = document.getElementById(`${tool}-panel`);
      if (panel) panel.oncancel = event => {
        event.preventDefault();
        onCloseRequested(tool);
      };
      if (panel && TOOL_PANELS[tool] === 'modal') panel.onclick = event => {
        if (event.target === panel) onCloseRequested(tool);
      };
    }
  }

  function show({tool, open, modal}) {
    const panel = document.getElementById(`${tool}-panel`);
    if (panel) showToolPanel(panel, {open, modal});
    document.getElementById(`open-${tool}`)?.setAttribute('aria-expanded', String(open));
  }

  return Object.freeze({mount, show});
}

function showToolPanel(panel, {open, modal}) {
  if (!open) {
    if (panel.open) panel.close();
  } else if (!panel.open) {
    if (modal) panel.showModal();
    else panel.show();
  }
}
