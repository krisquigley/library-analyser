// The playlist preview in the page (#138): a Preview button, its status and the list of tracks.
// It keeps only the elements it last mounted, to update them in place.

const PREVIEW_COLUMNS = Object.freeze([
  ['place', '#'], ['track', 'Track'], ['bpm', 'BPM'], ['key', 'Key'], ['energy', 'Energy'], ['target', 'Target'],
  ['transition', 'Transition']]);

export function playlistPreviewView({onPreviewRequested}) {
  let mounted = null;

  function show(update) {
    if (!mounted) return;
    if (update.previewDisabled !== undefined) mounted.button.disabled = update.previewDisabled;
    if (update.status) showStatus(mounted.status, update.status);
    if (update.rows) mounted.body.replaceChildren(...update.rows.map(previewRow));
  }

  function mount(panel, viewModel) {
    const button = element('button', {id: 'preview-playlist', type: 'button', textContent: 'Preview'});
    button.onclick = () => onPreviewRequested();
    const status = element('p', {id: 'playlist-preview-status', className: 'muted'});
    const heading = element('tr', {id: 'playlist-preview-heading'});
    heading.append(...PREVIEW_COLUMNS.map(([, caption]) => element('th', {scope: 'col', textContent: caption})));
    const head = element('thead', {});
    head.append(heading);
    const body = element('tbody', {id: 'playlist-preview-tracks'});
    const table = element('table', {className: 'playlist-preview-table'});
    table.append(head, body);
    const section = element('section', {id: 'playlist-preview'});
    section.setAttribute('aria-label', 'Playlist preview');
    section.append(button, status, table);
    panel.append(section);
    mounted = {button, status, body};
    show(viewModel);
  }

  return Object.freeze({mount, show});
}

function previewRow(row) {
  const line = element('tr', {});
  line.append(...PREVIEW_COLUMNS.map(([field]) => element('td', {textContent: row[field]})));
  return line;
}

function showStatus(status, {text, urgent}) {
  status.setAttribute('role', urgent ? 'alert' : 'status');
  status.setAttribute('aria-live', urgent ? 'assertive' : 'polite');
  status.textContent = text;
}

function element(tag, properties) {
  return Object.assign(document.createElement(tag), properties);
}
