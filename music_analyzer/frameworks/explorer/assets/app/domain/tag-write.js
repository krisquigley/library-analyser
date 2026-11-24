// The lifecycle of the page's tag-write action (#132), as a transitions table: only a previewed action can be applied,
// and a preview is discarded when the listener moves to another track.

const TAG_WRITE_TRANSITIONS = Object.freeze({
  idle: Object.freeze({preview: 'previewing'}),
  previewing: Object.freeze({succeed: 'previewed', fail: 'failed'}),
  previewed: Object.freeze({preview: 'previewing', apply: 'applying', discard: 'idle'}),
  applying: Object.freeze({succeed: 'applied', fail: 'failed'}),
  applied: Object.freeze({preview: 'previewing'}),
  failed: Object.freeze({preview: 'previewing'}),
});

export const TAG_WRITE_STATES = Object.freeze(Object.keys(TAG_WRITE_TRANSITIONS));

export class TagWriteTransitionError extends Error {}

export function nextTagWriteState(state, action) {
  const next = Object.hasOwn(TAG_WRITE_TRANSITIONS, state) && TAG_WRITE_TRANSITIONS[state][action];
  if (!next) throw new TagWriteTransitionError(`Tags cannot ${action} while ${state}`);
  return next;
}
