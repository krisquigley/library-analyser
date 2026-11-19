// The track detail panel (#146): the current track's metadata and evidence, from view models.

export function trackDetailView() {
  function show({heading, metadata: metadataView, fields}) {
    const root = document.getElementById('detail');
    root.setAttribute('aria-busy', 'false');
    const list = document.createElement('div');
    list.append(metadata(metadataView), ...fields.map(field));
    root.replaceChildren(setDetailText(document.createElement('h3'), heading), list);
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

  return Object.freeze({show, field, gauge, metadata});
}

function detailElement(tag, properties) {
  return Object.assign(document.createElement(tag), properties);
}

function setDetailText(element, value) {
  element.textContent = value == null ? '' : String(value);
  return element;
}
