// The tools the header opens over the graph (#233): the Library and the graph filters (#234) as drawers beside it, and
// the playlist generator and Write tags as centred modals, and the mood strip under the graph (#290). Each panel is
// closed or open; one drawer and one modal at most.

const TOOL_PANEL_TRANSITIONS = Object.freeze({
  closed: Object.freeze({open: 'open'}),
  open: Object.freeze({close: 'closed'}),
});

export const TOOL_PANEL_STATES = Object.freeze(Object.keys(TOOL_PANEL_TRANSITIONS));

export const TOOL_PANELS = Object.freeze({library: 'drawer', filters: 'drawer', playlist: 'modal', 'tag-write': 'modal', mood: 'strip'});

export class ToolPanelTransitionError extends Error {}

export function nextToolPanelState(state, action) {
  const next = Object.hasOwn(TOOL_PANEL_TRANSITIONS, state) && TOOL_PANEL_TRANSITIONS[state][action];
  if (!next) throw new ToolPanelTransitionError(`A tool panel cannot ${action} while ${state}`);
  return next;
}

export function isToolPanel(name) {
  return typeof name === 'string' && Object.hasOwn(TOOL_PANELS, name);
}

export function panelsDisplacedBy(tool, openTools) {
  return openTools.filter(other => other !== tool && TOOL_PANELS[other] === TOOL_PANELS[tool]);
}
