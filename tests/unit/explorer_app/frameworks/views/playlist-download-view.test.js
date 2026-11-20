// Issue #146: the Download M3U controls on screen, and the listener's input they report.
import {test, beforeEach} from 'node:test';
import assert from 'node:assert/strict';
import {playlistDownloadView} from '../../../../../music_explorer/frameworks/explorer/assets/app/frameworks/views/playlist-download-view.js';
import {byTag, descendants, fakeElement, installFakeDocument} from '../fake-document.js';

beforeEach(() => { installFakeDocument([]); });

const VALUES = Object.freeze({bpmMin: '', bpmMax: '', count: '10', durationMinutes: '', harmonicMixing: true,
  minimumKeyStrength: '0.5', energyArc: 'none', energyLow: '', energyHigh: '', moodHold: ''});
const viewModel = (changes = {}) => ({values: VALUES, minimumKeyStrengthDisabled: false, energyRangeDisabled: true,
  downloadDisabled: false, arcChoices: [['none', 'No energy arc'], ['rise', 'Rising energy']],
  moodChoices: [['', 'No mood hold'], ['happy', 'Hold mood: happy']], ...changes});

function mounted(changes) {
  const heard = {edited: [], downloads: []};
  const view = playlistDownloadView({onControlsEdited: values => heard.edited.push(values),
    onDownloadRequested: values => heard.downloads.push(values)});
  const panel = fakeElement('section');
  view.mount(panel, viewModel(changes));
  const byId = id => descendants(panel).find(node => node.id === id);
  return {view, heard, panel, byId, text: () => descendants(panel).map(node => node.textContent).join(' ')};
}

test('mounting draws the controls and asks for nothing until the listener clicks Download M3U', () => {
  const {heard, byId} = mounted();
  const button = byId('download-m3u');
  assert.deepEqual([button.type, button.textContent, button.disabled], ['button', 'Download M3U', false]);
  assert.deepEqual([heard.edited, heard.downloads], [[], []]);
  button.onclick();
  assert.deepEqual(heard.downloads, [VALUES]);
});

test('editing a control reports every control value, with harmonic mixing as a tick', () => {
  const {heard, byId} = mounted();
  byId('m3u-bpm-min').value = '120';
  byId('m3u-harmonic').checked = false;
  byId('m3u-harmonic').onchange();
  assert.deepEqual(heard.edited, [{...VALUES, bpmMin: '120', harmonicMixing: false}]);
});

test('the count and the optional target duration have their ranges', () => {
  const {byId} = mounted();
  const [count, duration] = [byId('m3u-count'), byId('m3u-duration')];
  assert.deepEqual([count.type, count.min, count.max, count.value], ['number', '1', '1000', '10']);
  assert.deepEqual([duration.type, duration.min, duration.max, duration.value, duration.placeholder],
    ['number', '1', '1440', '', 'minutes (optional)']);
});

test('harmonic mixing is a tick box, with its minimum key strength in its valid range', () => {
  const {byId, text} = mounted({minimumKeyStrengthDisabled: true});
  const [harmonic, strength] = [byId('m3u-harmonic'), byId('m3u-min-key-strength')];
  assert.deepEqual([harmonic.type, harmonic.checked], ['checkbox', true]);
  assert.deepEqual([strength.type, strength.min, strength.max, strength.step, strength.value, strength.disabled],
    ['number', '0', '1', '0.05', '0.5', true]);
  assert.ok(text().includes('Min key strength (0.0–1.0)'));
});

test('the energy arc and mood hold offer their choices, the moods coming from the graph', () => {
  const {byId} = mounted();
  const [arc, mood] = [byId('m3u-arc'), byId('m3u-mood')];
  assert.deepEqual(arc.children.map(option => [option.value, option.textContent]), [['none', 'No energy arc'], ['rise', 'Rising energy']]);
  assert.deepEqual(mood.children.map(option => [option.value, option.textContent]), [['', 'No mood hold'], ['happy', 'Hold mood: happy']]);
  assert.deepEqual([arc.value, mood.value], ['none', '']);
});

test('the energy range has its valid range, and is enabled only while an arc applies', () => {
  const {view, byId, text} = mounted();
  const [low, high] = [byId('m3u-energy-low'), byId('m3u-energy-high')];
  assert.deepEqual([low.type, low.min, low.max, low.step, low.value, low.placeholder, low.disabled],
    ['number', '0', '1', '0.05', '', '0.1', true]);
  assert.deepEqual([high.placeholder, high.disabled], ['0.9', true]);
  assert.ok(text().includes('Energy low (0.0–1.0)') && text().includes('Energy high (0.0–1.0)'));
  view.show({energyRangeDisabled: false, minimumKeyStrengthDisabled: true});
  assert.deepEqual([low.disabled, high.disabled, byId('m3u-min-key-strength').disabled], [false, false, true]);
});

test('the status is polite text, and urgent for a failure, never markup', () => {
  const {view, byId, panel} = mounted();
  const status = byId('m3u-download-status');
  assert.deepEqual([status.getAttribute('role'), status.getAttribute('aria-live')], ['status', 'polite']);
  view.show({downloadDisabled: false, status: {text: 'M3U downloaded. Warning: <b>dead end</b>', urgent: false}});
  assert.deepEqual([status.getAttribute('role'), status.textContent], ['status', 'M3U downloaded. Warning: <b>dead end</b>']);
  view.show({downloadDisabled: false, status: {text: 'M3U download failed: <img src=x>', urgent: true}});
  assert.deepEqual([status.getAttribute('role'), status.getAttribute('aria-live')], ['alert', 'assertive']);
  assert.ok(!descendants(panel).some(node => ['B', 'IMG'].includes(node.tagName)));
});

test('the button is disabled while a download is in flight, and nothing is shown before the controls are mounted', () => {
  const unmounted = playlistDownloadView({onControlsEdited() {}, onDownloadRequested() {}});
  assert.doesNotThrow(() => unmounted.show({downloadDisabled: true}));
  const {view, byId} = mounted();
  view.show({downloadDisabled: true});
  assert.equal(byId('download-m3u').disabled, true);
  assert.equal(byTag(byId('m3u-download-controls'), 'legend')[0].textContent, 'Download M3U');
});
