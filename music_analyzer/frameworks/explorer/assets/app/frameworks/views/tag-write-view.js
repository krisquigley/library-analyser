// The Write tags panel in the page (#132): what to tag and how, Preview tags, the changes to check, then Write these tags.

const TAG_WRITE_POLICIES = Object.freeze([
  {value: 'fill-empty', label: 'Fill empty tags only'},
  {value: 'replace-existing', label: 'Also replace existing tags'},
]);

export function tagWriteView({onPreviewRequested, onApplyRequested}) {
  let mounted = null;

  function mount(panel, viewModel) {
    const target = tagWriteElement('select', {id: 'tag-write-target'});
    target.setAttribute('aria-label', 'Tracks to tag');
    const selectedTrack = tagWriteElement('option', {value: 'selected-track', textContent: 'Selected track'});
    const playlist = tagWriteElement('option', {value: 'previewed-playlist'});
    target.append(selectedTrack, playlist);
    target.value = 'selected-track';
    const policy = tagWriteElement('select', {id: 'tag-write-policy'});
    policy.setAttribute('aria-label', 'Existing tags');
    policy.append(...TAG_WRITE_POLICIES.map(({value, label}) => tagWriteElement('option', {value, textContent: label})));
    policy.value = TAG_WRITE_POLICIES[0].value;
    const preview = tagWriteElement('button', {id: 'tag-write-preview', type: 'button', textContent: 'Preview tags'});
    const changes = tagWriteElement('tbody', {id: 'tag-write-changes'});
    const table = tagWriteElement('table', {id: 'tag-write-table'});
    table.append(changes);
    const skipped = tagWriteElement('ul', {id: 'tag-write-skipped', className: 'muted'});
    const apply = tagWriteElement('button', {id: 'tag-write-apply', type: 'button', textContent: 'Write these tags'});
    const report = tagWriteElement('ul', {id: 'tag-write-report'});
    const status = tagWriteElement('p', {id: 'tag-write-status', className: 'muted'});
    preview.onclick = () => onPreviewRequested(policy.value, target.value);
    apply.onclick = () => onApplyRequested();
    const section = tagWriteElement('section', {id: 'tag-write-controls'});
    section.append(target, policy, preview, table, skipped, apply, report, status);
    panel.append(section);
    mounted = {target, playlist, preview, apply, changes, skipped, report, status};
    show(viewModel);
  }

  function show(update) {
    if (!mounted) return;
    if (update.busy !== undefined) mounted.preview.disabled = update.busy;
    if (update.canApply !== undefined || update.busy !== undefined) mounted.apply.disabled = Boolean(update.busy) || !update.canApply;
    if (update.rows) mounted.changes.replaceChildren(...update.rows.map(tagWriteRow));
    if (update.skipped) mounted.skipped.replaceChildren(...update.skipped.map(tagWriteListItem));
    if (update.report) mounted.report.replaceChildren(...update.report.map(tagWriteListItem));
    if (update.status) showTagWriteStatus(mounted.status, update.status);
    if (update.playlistTarget) showPlaylistTarget(mounted, update.playlistTarget);
  }

  return Object.freeze({mount, show});
}

function tagWriteRow({file, field, change}) {
  const row = tagWriteElement('tr', {});
  row.append(...[file, field, change].map(text => tagWriteElement('td', {textContent: text})));
  return row;
}

function tagWriteListItem(text) {
  return tagWriteElement('li', {textContent: text});
}

function showPlaylistTarget({target, playlist}, {available, label}) {
  playlist.disabled = !available;
  playlist.textContent = label;
  if (!available && target.value === 'previewed-playlist') target.value = 'selected-track';
}

function showTagWriteStatus(status, {text, urgent}) {
  status.setAttribute('role', urgent ? 'alert' : 'status');
  status.setAttribute('aria-live', urgent ? 'assertive' : 'polite');
  status.textContent = text;
}

function tagWriteElement(tag, properties) {
  return Object.assign(document.createElement(tag), properties);
}
