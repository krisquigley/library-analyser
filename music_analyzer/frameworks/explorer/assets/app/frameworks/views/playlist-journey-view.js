// The journey chart under the hand-built playlist (#294), drawn from its view model: one lane per measure on a shared
// time axis, each named on the chart and in its toggle, with the track under the pointer read out below. Which lanes
// are shown is the listener's view of the chart, kept by the toggles themselves, as the mood strip's picker keeps its
// position.

// The categorical slots for a dark surface, in fixed order (validated: 4 slots on #101a2a, all checks pass).
const LANE_COLORS = Object.freeze({bpm: '#3987e5', key: '#d95926', arousal: '#199e70', valence: '#c98500'});
const LANE_HEIGHT = 34;
const LABEL_GUTTER = 96;
const LANE_GAP = 10;
const AXIS_HEIGHT = 18;
const GRID_COLOR = 'rgba(255,255,255,0.08)';
const TEXT_FALLBACK = '#9aa7bd';

export function playlistJourneyView() {
  let built = null;
  let shownModel = null;

  function chart() {
    const host = document.getElementById('playlist-journey');
    if (host && !built) built = buildJourney(host, () => redraw());
    return built;
  }

  function show(model) {
    const parts = chart();
    if (!parts) return;
    shownModel = model;
    parts.host.hidden = model.hidden;
    if (model.hidden) return;
    parts.caption.textContent = model.caption;
    for (const lane of model.lanes) parts.toggles[lane.measure].label.textContent = `${lane.label} ${lane.range}`;
    parts.canvas.onpointermove = event => {
      const bounds = parts.canvas.getBoundingClientRect();
      const at = (event.clientX - bounds.left - LABEL_GUTTER) / (bounds.width - LABEL_GUTTER);
      parts.readout.textContent = model.stops.find(stop => at >= stop.from && at < stop.to)?.readout ?? '';
    };
    parts.canvas.onpointerleave = () => { parts.readout.textContent = ''; };
    redraw();
  }

  function redraw() {
    if (!built || !shownModel || shownModel.hidden) return;
    const lanes = shownModel.lanes.filter(lane => built.toggles[lane.measure].box.checked);
    drawJourney(built.canvas, {lanes, ticks: shownModel.ticks});
  }

  return Object.freeze({show});
}

function buildJourney(host, onToggled) {
  const heading = journeyElement('h2', {id: 'playlist-journey-heading', textContent: 'Journey'});
  const caption = journeyElement('p', {id: 'playlist-journey-caption', className: 'muted'});
  const legend = journeyElement('div', {className: 'playlist-journey-lanes', role: 'group'});
  legend.setAttribute('aria-label', 'Lanes shown');
  const toggles = {};
  for (const [measure, color] of Object.entries(LANE_COLORS)) {
    const box = journeyElement('input', {type: 'checkbox', id: `journey-show-${measure}`, checked: true});
    box.onchange = onToggled;
    const label = journeyElement('label', {htmlFor: box.id});
    label.style.setProperty?.('--lane-color', color);
    legend.append(box, label);
    toggles[measure] = {box, label};
  }
  const canvas = journeyElement('canvas', {id: 'playlist-journey-chart'});
  canvas.setAttribute('role', 'img');
  canvas.setAttribute('aria-label', 'BPM, key, arousal and valence of each track over the length of the playlist; the table above lists them');
  const readout = journeyElement('output', {id: 'playlist-journey-readout'});
  readout.setAttribute('aria-live', 'polite');
  host.replaceChildren(heading, caption, legend, canvas, readout);
  return {host, caption, toggles, canvas, readout};
}

function drawJourney(canvas, {lanes, ticks}) {
  const width = canvas.clientWidth || 0;
  const height = lanes.length * (LANE_HEIGHT + LANE_GAP) + AXIS_HEIGHT;
  const scale = globalThis.devicePixelRatio || 1;
  canvas.width = Math.round(width * scale);
  canvas.height = Math.round(height * scale);
  canvas.style.height = `${height}px`;
  const context = canvas.getContext?.('2d');
  if (!context) return;
  context.setTransform(scale, 0, 0, scale, 0, 0);
  context.clearRect(0, 0, width, height);
  const text = textColor(canvas);
  context.font = '11px system-ui, sans-serif';
  context.textBaseline = 'top';
  const plot = {left: LABEL_GUTTER, width: Math.max(0, width - LABEL_GUTTER)};
  lanes.forEach((lane, place) => drawLane(context, lane, {top: place * (LANE_HEIGHT + LANE_GAP) + LANE_GAP, plot, text}));
  drawTicks(context, ticks, {top: height - AXIS_HEIGHT, plot, text});
}

function drawLane(context, lane, {top, plot, text}) {
  const bottom = top + LANE_HEIGHT;
  const x = at => plot.left + at * plot.width;
  context.strokeStyle = GRID_COLOR;
  context.lineWidth = 1;
  context.beginPath();
  context.moveTo(plot.left, bottom + 0.5);
  context.lineTo(plot.left + plot.width, bottom + 0.5);
  context.stroke();
  context.fillStyle = text;
  context.fillText(lane.label, 0, top + LANE_HEIGHT / 2 - 6);
  context.strokeStyle = LANE_COLORS[lane.measure];
  context.lineWidth = 2;
  context.lineJoin = 'round';
  context.lineCap = 'round';
  const y = level => bottom - 3 - level * (LANE_HEIGHT - 6);
  let drawing = false;
  context.beginPath();
  for (const step of lane.steps) {
    if (step.level === null) {
      drawing = false;
      continue;
    }
    if (drawing) context.lineTo(x(step.from), y(step.level));
    else context.moveTo(x(step.from), y(step.level));
    context.lineTo(x(step.to), y(step.level));
    drawing = true;
  }
  context.stroke();
}

function drawTicks(context, ticks, {top, plot, text}) {
  context.fillStyle = text;
  context.strokeStyle = GRID_COLOR;
  context.lineWidth = 1;
  for (const tick of ticks) {
    const x = plot.left + Math.min(plot.width - 1, Math.max(1, tick.at * plot.width));
    context.beginPath();
    context.moveTo(x + 0.5, top);
    context.lineTo(x + 0.5, top + 4);
    context.stroke();
    context.textAlign = tick.at === 0 ? 'left' : (tick.at >= 0.95 ? 'right' : 'center');
    context.fillText(tick.text, x, top + 5);
  }
  context.textAlign = 'left';
}

function textColor(canvas) {
  const color = globalThis.getComputedStyle?.(canvas)?.color;
  return color || TEXT_FALLBACK;
}

function journeyElement(tag, properties) {
  return Object.assign(document.createElement(tag), properties);
}
