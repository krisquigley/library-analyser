// Refreshing the library view (#146): a transitions table over one refresh. A newer refresh may begin from any state;
// one in flight may fail, or yield when the listener has chosen another track meanwhile, which ends its loading.

const IN_FLIGHT = Object.freeze({begin: 'preparing', fail: 'failed', yield: 'loaded'});

const LIBRARY_REFRESH_TRANSITIONS = Object.freeze({
  idle: Object.freeze({begin: 'preparing'}),
  preparing: Object.freeze({...IN_FLIGHT, read: 'reading'}),
  reading: Object.freeze({...IN_FLIGHT, finish: 'loaded'}),
  loaded: Object.freeze({begin: 'preparing'}),
  failed: Object.freeze({begin: 'preparing'}),
});

export const LIBRARY_REFRESH_STATES = Object.freeze(Object.keys(LIBRARY_REFRESH_TRANSITIONS));

export class LibraryRefreshTransitionError extends Error {}

export function nextLibraryRefreshState(state, action) {
  const next = Object.hasOwn(LIBRARY_REFRESH_TRANSITIONS, state) && LIBRARY_REFRESH_TRANSITIONS[state][action];
  if (!next) throw new LibraryRefreshTransitionError(`A library refresh cannot ${action} while ${state}`);
  return next;
}
