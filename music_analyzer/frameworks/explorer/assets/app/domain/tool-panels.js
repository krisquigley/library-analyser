// The tools the header opens over the graph (#233): the Library as a drawer beside it, and the playlist generator and
// Write tags as centred modals. Each panel is closed or open; only one modal is open at a time.

const TOOL_PANEL_TRANSITIONS = Object.freeze({
  closed: Object.freeze({open: 'open'}),
  open: Object.freeze({close: 'closed'}),
});

export const TOOL_PANEL_STATES = Object.freeze(Object.keys(TOOL_PANEL_TRANSITIONS));

export const TOOL_PANELS = Object.freeze({library: 'drawer', playlist: 'modal', 'tag-write': 'modal'});

export class ToolPanelTransitionError extends Error {}

export function nextToolPanelState(state, action) {
  const next = Object.hasOwn(TOOL_PANEL_TRANSITIONS, state) && TOOL_PANEL_TRANSITIONS[state][action];
  if (!next) throw new ToolPanelTransitionError(`A tool panel cannot ${action} while ${state}`);
  return next;
}

export function isToolPanel(name) {
  return typeof name === 'string' && Object.hasOwn(TOOL_PANELS, name);
}

export function modalsDisplacedBy(tool, openTools) {
  if (TOOL_PANELS[tool] !== 'modal') return [];
  return openTools.filter(other => other !== tool && TOOL_PANELS[other] === 'modal');
}
