// The mood strip's canvas, picker and readout (#146), drawn from its view model.
// The picker's position is the listener's inspection of the strip, kept by the picker element itself.

import {nearestMarkIndex} from '../../adapters/presenters/mood-strip-presenter.js';

const LINE_COLOR = '#444';
const MARK_COLOR = '#164e8c';
const SELECTED_COLOR = '#b02212';

export function moodStripView() {
  const elements = () => ({canvas: document.getElementById('mood-strip'), picker: document.getElementById('mood-strip-picker'),
    readout: document.getElementById('mood-strip-value')});

  function width() {
    const {canvas} = elements();
    return canvas ? canvas.clientWidth : 0;
  }

  function show(view) {
    const {canvas, picker, readout} = elements();
    if (!canvas || !picker || !readout) return;
    draw(canvas, view);
    picker.max = String(view.pickerMax);
    picker.disabled = view.disabled;
    picker.value = String(view.index);
    const showReadout = () => { readout.textContent = view.marks.length ? view.readouts[Number(picker.value)] : view.emptyReadout; };
    picker.oninput = showReadout;
    showReadout();
    canvas.onclick = event => {
      if (!view.marks.length) return;
      const bounds = canvas.getBoundingClientRect();
      picker.value = String(nearestMarkIndex(view, (event.clientX - bounds.left) * view.width / bounds.width));
      showReadout();
    };
  }

  return Object.freeze({width, show});
}

function draw(canvas, view) {
  const context = canvas.getContext('2d');
  canvas.width = view.width;
  canvas.height = view.height;
  context.clearRect(0, 0, view.width, view.height);
  context.strokeStyle = LINE_COLOR;
  context.beginPath();
  context.moveTo(view.padding, view.baseline);
  context.lineTo(view.width - view.padding, view.baseline);
  context.stroke();
  for (const mark of view.marks.filter(each => !each.selected)) drawMark(context, mark, 3, MARK_COLOR);
  for (const mark of view.marks.filter(each => each.selected)) drawMark(context, mark, 5, SELECTED_COLOR);
}

function drawMark(context, {x, y}, radius, color) {
  context.beginPath();
  context.arc(x, y, radius, 0, Math.PI * 2);
  context.fillStyle = color;
  context.fill();
}
