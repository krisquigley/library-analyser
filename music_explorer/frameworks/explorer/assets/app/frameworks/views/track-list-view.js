// The track list and its search box (#146): renders view models and reports the listener's input.

export function trackListView({onTrackChosen, onQueryTyped, onLoadMore, onRetry}) {
  function wireSearch() {
    const search = document.getElementById('track-search');
    if (!search || search.dataset.summarySearchWired) return;
    search.dataset.summarySearchWired = '1';
    search.oninput = () => onQueryTyped(search.value);
  }

  function show(view) {
    const root = document.getElementById('tracks');
    if (!root) return;
    const children = [trackTable(view, onTrackChosen), trackListStatusLine(view.status)];
    if (view.loadMore) children.push(loadMoreNav(view.loadMore, onLoadMore));
    if (view.retry) children.push(trackListButton('Retry search', onRetry));
    children.push(emptySearchMessage(view));
    root.setAttribute('aria-busy', view.busy ? 'true' : 'false');
    root.replaceChildren(...children);
    wireSearch();
  }

  return Object.freeze({show});
}

function trackTable(view, onTrackChosen) {
  const table = trackListElement('table', {className: 'tracks-table'});
  table.append(setTrackListText(document.createElement('caption'), view.caption));
  const headRow = document.createElement('tr');
  for (const label of ['Title', 'Artist']) headRow.append(setTrackListText(document.createElement('th'), label));
  const head = document.createElement('thead');
  head.append(headRow);
  const body = document.createElement('tbody');
  body.replaceChildren(...view.rows.map(row => trackRow(row, onTrackChosen)));
  table.append(head, body);
  return table;
}

function trackRow({trackId, title, artist, current}, onTrackChosen) {
  const row = trackListElement('tr', {className: current ? 'current' : ''});
  Object.assign(row.dataset, {trackId, title, artist});
  const button = setTrackListText(document.createElement('button'), title);
  button.onclick = () => onTrackChosen(trackId);
  if (current) button.setAttribute('aria-current', 'true');
  const titleCell = document.createElement('td');
  titleCell.append(button);
  row.append(titleCell, setTrackListText(document.createElement('td'), artist));
  return row;
}

function trackListStatusLine(text) {
  const status = trackListElement('p', {className: 'muted'});
  status.setAttribute('role', 'status');
  status.setAttribute('aria-live', 'polite');
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
