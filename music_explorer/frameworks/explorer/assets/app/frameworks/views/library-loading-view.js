// The library loading screen (#146), drawn from its view model. Its stage is a class on the surface, beside the
// surface's own classes; the surface is never busy, so the page stays usable while the library refreshes.

const STAGES = Object.freeze(['active', 'refresh', 'error', 'done']);

export function libraryLoadingView({onRetry}) {
  const elements = () => ({surface: document.getElementById('loading-surface'), status: document.getElementById('loading-status'),
    error: document.getElementById('loading-error'), retry: document.getElementById('loading-retry')});

  function mount() {
    const {retry} = elements();
    if (retry) retry.onclick = () => onRetry();
  }

  function show(screen) {
    const {surface, status, error, retry} = elements();
    if (surface) {
      surface.classList.remove(...STAGES);
      surface.classList.add(screen.stage);
      surface.setAttribute('aria-busy', 'false');
      surface.hidden = screen.hidden;
    }
    if (status) {
      status.textContent = screen.statusText;
      status.setAttribute('role', 'status');
    }
    if (error) {
      error.textContent = screen.errorText;
      if (screen.errorShown) error.setAttribute('role', 'alert');
      error.hidden = !screen.errorShown;
    }
    if (retry) retry.hidden = !screen.retryShown;
  }

  return Object.freeze({mount, show});
}
