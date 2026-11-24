// The track list and its search box (#146): renders view models and reports the listener's input. Each result is a
// row, the title over the artist (#235); the up and down arrow keys move between rows.

export function trackListView({onTrackChosen, onQueryTyped, onLoadMore, onRetry}) {
  let shownRows = null;

  function wireSearch() {
    const search = document.getElementById('track-search');
    if (!search || search.dataset.summarySearchWired) return;
    search.dataset.summarySearchWired = '1';
    search.oninput = () => onQueryTyped(search.value);
  }

  function show(view) {
    const root = document.getElementById('tracks');
    if (!root) return;
    const table = trackTable(view, onTrackChosen);
    shownRows = table.trackRows;
    const children = [table, trackListStatusLine(view)];
    if (view.loadMore) children.push(loadMoreNav(view.loadMore, onLoadMore));
    if (view.retry) children.push(trackListButton('Retry search', onRetry));
    children.push(emptySearchMessage(view));
    root.setAttribute('aria-busy', view.busy ? 'true' : 'false');
    root.dataset.tone = view.tone;
    root.replaceChildren(...children);
    wireSearch();
  }

  // Badges arrive once the graph has loaded; the rows stay, so a click on one is never lost to a redraw.
  function showBpmBadges(badges) {
    if (!shownRows) return;
    const byTrack = new Map(badges.map(({trackId, bpmBadge}) => [trackId, bpmBadge]));
    for (const row of Array.from(shownRows.children)) {
      if (byTrack.has(row.dataset.trackId)) setBpmBadge(row.artistCell, byTrack.get(row.dataset.trackId));
    }
  }

  return Object.freeze({show, showBpmBadges});
}

function trackTable(view, onTrackChosen) {
  const table = trackListElement('table', {className: 'tracks-table'});
  table.append(setTrackListText(trackListElement('caption', {className: 'visually-hidden'}), view.caption));
  const headRow = document.createElement('tr');
  for (const label of ['Title', 'Artist']) headRow.append(setTrackListText(document.createElement('th'), label));
  const head = trackListElement('thead', {className: 'visually-hidden'});
  head.append(headRow);
  const body = document.createElement('tbody');
  body.replaceChildren(...view.rows.map(row => trackRow(row, onTrackChosen)));
  body.onkeydown = event => moveBetweenRows(body, event);
  table.trackRows = body;
  table.append(head, body);
  return table;
}

function trackRow({trackId, title, artist, bpmBadge, current}, onTrackChosen) {
  const row = trackListElement('tr', {className: current ? 'current' : ''});
  Object.assign(row.dataset, {trackId, title, artist});
  const button = setTrackListText(trackListElement('button', {type: 'button'}), title);
  button.onclick = () => onTrackChosen(trackId);
  if (current) button.setAttribute('aria-current', 'true');
  const titleCell = trackListElement('td', {className: 'track-title'});
  titleCell.append(button);
  const artistCell = setTrackListText(trackListElement('td', {className: 'track-artist'}), artist);
  setBpmBadge(artistCell, bpmBadge);
  row.append(titleCell, artistCell);
  Object.assign(row, {trackButton: button, artistCell});
  return row;
}

function setBpmBadge(artistCell, bpmBadge) {
  artistCell.bpmBadge?.remove();
  artistCell.bpmBadge = bpmBadge ? setTrackListText(trackListElement('span', {className: 'track-badge'}), bpmBadge) : null;
  if (artistCell.bpmBadge) artistCell.append(artistCell.bpmBadge);
}

const ROW_STEPS = Object.freeze({ArrowDown: 1, ArrowUp: -1});

function moveBetweenRows(body, event) {
  if (!Object.hasOwn(ROW_STEPS, event.key)) return;
  const buttons = Array.from(body.children, row => row.trackButton);
  const here = buttons.findIndex(button => button === event.target);
  const next = buttons[here + ROW_STEPS[event.key]];
  if (here < 0 || !next) return;
  event.preventDefault();
  next.focus();
}

function trackListStatusLine({status: text, tone}) {
  const status = trackListElement('p', {className: tone === 'failed' ? 'track-list-status failed' : 'track-list-status muted'});
  status.setAttribute('role', tone === 'failed' ? 'alert' : 'status');
  status.setAttribute('aria-live', tone === 'failed' ? 'assertive' : 'polite');
  return setTrackListText(status, text);
}

function loadMoreNav({disabled}, onLoadMore) {
  const nav = document.createElement('nav');
  nav.setAttribute('aria-label', 'Track list pagination');
  const more = trackListButton('Load more tracks', onLoadMore);
  more.disabled = disabled;
  nav.append(more);
  return nav;
}

function emptySearchMessage({emptyMessage, emptyHidden}) {
  const empty = trackListElement('p', {id: 'track-search-empty', className: 'muted'});
  empty.setAttribute('role', 'status');
  setTrackListText(empty, emptyMessage);
  empty.hidden = emptyHidden;
  return empty;
}

function trackListButton(label, onClick) {
  const button = trackListElement('button', {type: 'button'});
  button.onclick = () => onClick();
  return setTrackListText(button, label);
}

function trackListElement(tag, properties) {
  return Object.assign(document.createElement(tag), properties);
}

function setTrackListText(element, value) {
  element.textContent = value == null ? '' : String(value);
  return element;
}
