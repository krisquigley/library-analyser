// The library loading screen as each refresh event leaves it (#146).

const WORKING = Object.freeze({stage: 'refresh', hidden: false, errorText: '', errorShown: false, retryShown: false});
const DONE = Object.freeze({stage: 'done', hidden: true, statusText: 'Library loaded', errorText: '', errorShown: false,
  retryShown: false});

const LOADING_SCREENS = Object.freeze({
  'library-refresh-started': () => ({...WORKING, statusText: 'Preparing library view'}),
  'library-state-loading': () => ({...WORKING, statusText: 'Loading library state'}),
  'library-loaded': () => ({...DONE}),
  'library-refresh-yielded': () => ({...DONE}),
  'library-refresh-failed': event => ({stage: 'refresh', hidden: false, statusText: 'Unable to load library',
    errorText: event.message, errorShown: true, retryShown: true}),
});

export function presentLibraryRefreshEvent(event) {
  const screen = LOADING_SCREENS[event.type];
  return screen ? screen(event) : null;
}
