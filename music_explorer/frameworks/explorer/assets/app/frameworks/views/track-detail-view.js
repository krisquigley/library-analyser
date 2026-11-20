// The track detail panel (#146): the current track's metadata and evidence, from view models.

export function trackDetailView() {
  function show({heading, metadata: metadataView, fields}) {
    const root = document.getElementById('detail');
    root.setAttribute('aria-busy', 'false');
    const list = document.createElement('div');
    list.append(metadata(metadataView), ...fields.map(field));
    root.replaceChildren(setDetailText(document.createElement('h3'), heading), list);
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
      ...items.map(item => (item.gauge ? gauge(item.gauge) : setDetailText(document.createElement('p'), item.text))));
    return section;
  }

  function gauge({label, ariaLabel, needleDegrees}) {
    const dial = detailElement('div', {className: 'score-gauge'});
    dial.setAttribute('role', 'img');
    dial.setAttribute('aria-label', ariaLabel);
    const needle = detailElement('span', {className: 'score-needle'});
    needle.style.transform = `rotate(${needleDegrees}deg)`;
    dial.append(detailElement('span', {className: 'score-arc'}), needle, detailElement('span', {className: 'score-hub'}));
    const row = detailElement('div', {className: 'score-row'});
    row.append(setDetailText(document.createElement('span'), label), dial);
    return row;
  }

  function metadata({lines}) {
    const section = detailElement('section', {className: 'field track-metadata'});
    section.append(...lines.map(line => setDetailText(document.createElement('p'), line)));
    return section;
  }

  return Object.freeze({show, showNone, showLoading, showFailure, field, gauge, metadata});
}

function detailElement(tag, properties) {
  return Object.assign(document.createElement(tag), properties);
}

function setDetailText(element, value) {
  element.textContent = value == null ? '' : String(value);
  return element;
}
