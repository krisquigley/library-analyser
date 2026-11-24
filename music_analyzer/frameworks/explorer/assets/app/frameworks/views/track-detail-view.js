// The track detail panel (#146): the current track's metadata and evidence, from view models.

export function trackDetailView() {
  function show(viewModel) {
    const root = document.getElementById('detail');
    root.setAttribute('aria-busy', 'false');
    root.replaceChildren(setDetailText(document.createElement('h3'), viewModel.heading), fieldList(viewModel));
  }

  // The detail's field list, as shown: also drawn, detached, for the diagnostics to compare against (#236).
  function fieldList({metadata: metadataView, fields, unavailable}) {
    const list = document.createElement('div');
    list.append(metadata(metadataView), ...fields.map(field));
    if (unavailable) list.append(unavailableEvidenceSection(unavailable));
    return list;
  }

  // The panel may be absent while the page is still being built; there is then nothing to say.
  function showNone() {
    const root = document.getElementById('detail');
    if (!root) return;
    root.setAttribute('aria-busy', 'false');
    root.replaceChildren();
  }

  function showLoading({status}) {
    const root = document.getElementById('detail');
    if (!root) return;
    const line = setDetailText(document.createElement('p'), status);
    line.setAttribute('role', 'status');
    line.setAttribute('aria-live', 'polite');
    root.setAttribute('aria-busy', 'true');
    root.replaceChildren(line);
  }

  function showFailure({alert}, onRetry) {
    const root = document.getElementById('detail');
    if (!root) return;
    const line = setDetailText(document.createElement('p'), alert);
    line.setAttribute('role', 'alert');
    root.setAttribute('aria-busy', 'false');
    root.replaceChildren(line);
    if (!onRetry) return;
    const retry = setDetailText(detailElement('button', {type: 'button'}), 'Retry detail');
    retry.onclick = onRetry;
    root.append(retry);
  }

  function field({name, items}) {
    const section = detailElement('section', {className: 'field'});
    section.append(setDetailText(document.createElement('h4'), name),
      ...items.map(item => (item.bar ? bar(item.bar) : setDetailText(document.createElement('p'), item.text))));
    return section;
  }

  function bar({label, ariaLabel, valueText, fillPercent}) {
    const track = detailElement('span', {className: 'score-bar-track'});
    track.setAttribute('role', 'img');
    track.setAttribute('aria-label', ariaLabel);
    const fill = detailElement('span', {className: 'score-bar-fill'});
    fill.style.width = `${fillPercent}%`;
    track.append(fill);
    const row = detailElement('div', {className: 'score-bar'});
    row.append(setDetailText(detailElement('span', {className: 'score-bar-label'}), label), track,
      setDetailText(detailElement('span', {className: 'score-bar-value'}), valueText));
    return row;
  }

  function metadata({lines, keyFacts = []}) {
    const section = detailElement('section', {className: 'field track-metadata'});
    if (keyFacts.length) section.append(keyFactBadges(keyFacts));
    section.append(...lines.map(line => setDetailText(document.createElement('p'), line)));
    return section;
  }

  return Object.freeze({show, fieldList, showNone, showLoading, showFailure, field, bar, metadata});
}

function keyFactBadges(keyFacts) {
  const badges = detailElement('div', {className: 'key-facts'});
  badges.append(...keyFacts.map(({text, source}) => {
    const badge = setDetailText(detailElement('span', {className: 'key-fact', title: source}), text);
    badge.setAttribute('aria-label', `${text}, from ${source}`);
    return badge;
  }));
  return badges;
}

// Fields without usable evidence share one section; expanding it gives each field's reason.
function unavailableEvidenceSection({summary, reasons}) {
  const details = document.createElement('details');
  details.append(setDetailText(document.createElement('summary'), summary),
    ...reasons.map(({name, text}) => setDetailText(document.createElement('p'), `${name}: ${text}`)));
  const section = detailElement('section', {className: 'field unavailable-evidence'});
  section.append(details);
  return section;
}

function detailElement(tag, properties) {
  return Object.assign(document.createElement(tag), properties);
}

function setDetailText(element, value) {
  element.textContent = value == null ? '' : String(value);
  return element;
}
