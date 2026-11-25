// Issues #146 and #137: the Download M3U controls and the energy arc editor on screen, and the input they report.
import {test, beforeEach} from 'node:test';
import assert from 'node:assert/strict';
import {playlistDownloadView} from '../../../../../music_explorer/frameworks/explorer/assets/app/frameworks/views/playlist-download-view.js';
import {createInMemorySession} from '../../../../../music_explorer/frameworks/explorer/assets/app/frameworks/in-memory-session.js';
import {EMPTY_PLAYLIST_DRAFT} from '../../../../../music_explorer/frameworks/explorer/assets/app/domain/playlist-draft.js';
import {descendants, fakeElement, installFakeDocument} from '../fake-document.js';

beforeEach(() => { installFakeDocument([]); });

const VALUES = Object.freeze({bpmMin: '', bpmMax: '', count: '10', durationMinutes: '', harmonicMixing: true,
  minimumKeyStrength: '0.5', arcLengthUnit: 'tracks', moodHold: ''});
const DRAFT = Object.freeze({...VALUES, energyArcs: []});
const ARC = Object.freeze({shape: 'rise', length: '', low: '', high: '', canMoveEarlier: false, canMoveLater: false});
const viewModel = (changes = {}) => ({values: DRAFT, minimumKeyStrengthDisabled: false, lengthDisabled: false,
  arcs: [], arcLengthUnit: 'tracks', downloadDisabled: false,
  arcShapeChoices: [['rise', 'Rising energy'], ['peak', 'Energy peak']],
  arcLengthUnitChoices: [['tracks', 'Tracks'], ['minutes', 'Minutes']],
  moodChoices: [['', 'No mood hold'], ['happy', 'Hold mood: happy']],
  arousalRange: 'Library arousal: not known until the graph has placed tracks with arousal.', ...changes});

function mounted(changes) {
  const heard = {edited: [], downloads: [], arcs: []};
  const view = playlistDownloadView({onControlsEdited: values => heard.edited.push(values),
    onDownloadRequested: values => heard.downloads.push(values),
    onArcAdded: () => heard.arcs.push(['add']), onArcRemoved: place => heard.arcs.push(['remove', place]),
    onArcMoved: (place, offset) => heard.arcs.push(['move', place, offset]),
    onArcEdited: (place, fields) => heard.arcs.push(['edit', place, fields])});
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

test('the mood hold offers its choices, the moods coming from the graph', () => {
  const {byId} = mounted();
  const mood = byId('m3u-mood');
  assert.deepEqual(mood.children.map(option => [option.value, option.textContent]), [['', 'No mood hold'], ['happy', 'Hold mood: happy']]);
  assert.equal(mood.value, '');
});

test('the arc editor starts empty, with one Length in choice and an Add button', () => {
  const {heard, byId, text} = mounted();
  const [unit, rows, add] = [byId('m3u-arc-unit'), byId('m3u-arc-rows'), byId('m3u-add-arc')];
  assert.deepEqual(unit.children.map(option => [option.value, option.textContent]), [['tracks', 'Tracks'], ['minutes', 'Minutes']]);
  assert.deepEqual([unit.value, rows.children, add.textContent], ['tracks', [], 'Add energy arc']);
  assert.ok(text().includes('Energy arcs') && text().includes('Length in'));
  add.onclick();
  assert.deepEqual(heard.arcs, [['add']]);
  unit.value = 'minutes';
  unit.onchange();
  assert.deepEqual(heard.edited, [{...VALUES, arcLengthUnit: 'minutes'}]);
});

test('each arc row has its shape, length and energy range, and reports the whole row when edited', () => {
  const {heard, byId} = mounted({arcs: [ARC, {...ARC, shape: 'peak', length: '6', high: '0.9', canMoveEarlier: true}],
    arcLengthUnit: 'minutes'});
  assert.equal(byId('m3u-arc-rows').children.length, 2);
  const [shape, length, low, high] = ['shape', 'length', 'low', 'high'].map(field => byId(`m3u-arc-${field}-1`));
  assert.deepEqual([shape.value, length.value, low.value, high.value], ['peak', '6', '', '0.9']);
  assert.deepEqual([length.type, length.min, length.placeholder, length.getAttribute('aria-label')],
    ['number', '0', 'minutes', 'Arc 2 length in minutes']);
  // #265: raw arousal, as the graph shows it; a blank end follows the eligible tracks.
  assert.deepEqual([low.step, low.placeholder, high.placeholder], ['0.1', 'default', 'default']);
  assert.ok(!('min' in low) && !('max' in high), 'no 0-1 bounds');
  assert.match(low.title, /arousal as the graph shows it/);
  assert.equal(shape.getAttribute('aria-label'), 'Arc 2 shape');
  low.value = '0.3';
  low.onchange();
  assert.deepEqual(heard.arcs, [['edit', 1, {shape: 'peak', length: '6', low: '0.3', high: '0.9'}]]);
});

test('an arc row moves earlier or later only where it can, and can be removed', () => {
  const {heard, byId} = mounted({arcs: [{...ARC, canMoveLater: true}, {...ARC, canMoveEarlier: true}]});
  assert.deepEqual([byId('m3u-arc-earlier-0').disabled, byId('m3u-arc-later-0').disabled], [true, false]);
  assert.deepEqual([byId('m3u-arc-earlier-1').disabled, byId('m3u-arc-later-1').disabled], [false, true]);
  byId('m3u-arc-later-0').onclick();
  byId('m3u-arc-earlier-1').onclick();
  byId('m3u-arc-remove-1').onclick();
  assert.deepEqual(heard.arcs, [['move', 0, 1], ['move', 1, -1], ['remove', 1]]);
  assert.equal(byId('m3u-arc-remove-1').getAttribute('aria-label'), 'Remove arc 2');
});

test('an edited chain of the same size updates its rows in place, keeping the focused field', () => {
  const {view, byId} = mounted({arcs: [ARC, ARC]});
  const focused = byId('m3u-arc-low-1');
  view.show({arcs: [{...ARC, shape: 'peak', canMoveLater: true}, {...ARC, low: '0.2', canMoveEarlier: true}],
    arcLengthUnit: 'minutes'});
  assert.equal(byId('m3u-arc-low-1'), focused);
  assert.deepEqual([byId('m3u-arc-shape-0').value, focused.value, byId('m3u-arc-length-0').placeholder],
    ['peak', '0.2', 'minutes']);
  assert.deepEqual([byId('m3u-arc-later-0').disabled, byId('m3u-arc-earlier-1').disabled], [false, false]);
});

test('adding or removing an arc redraws the rows', () => {
  const {view, byId} = mounted({arcs: [ARC]});
  view.show({arcs: [ARC, {...ARC, shape: 'peak'}], arcLengthUnit: 'tracks'});
  assert.deepEqual([byId('m3u-arc-rows').children.length, byId('m3u-arc-shape-1').value], [2, 'peak']);
  view.show({arcs: [], arcLengthUnit: 'tracks'});
  assert.deepEqual(byId('m3u-arc-rows').children, []);
});

test("the track count and duration are disabled while the arcs' lengths set the playlist's", () => {
  const {view, byId} = mounted({lengthDisabled: true});
  assert.deepEqual([byId('m3u-count').disabled, byId('m3u-duration').disabled], [true, true]);
  view.show({lengthDisabled: false, minimumKeyStrengthDisabled: true});
  assert.deepEqual([byId('m3u-count').disabled, byId('m3u-duration').disabled, byId('m3u-min-key-strength').disabled],
    [false, false, true]);
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
});

test("composed with the real controller and use case, the arc editor's input reaches the M3U address", async () => {
  const root = '../../../../../music_explorer/frameworks/explorer/assets/app';
  const {createPlaylistDownload} = await import(`${root}/application/download-playlist/download-playlist.js`);
  const {playlistDownloadController} = await import(`${root}/adapters/controllers/playlist-download-controller.js`);
  const {playlistControlsViewModel, presentPlaylistDownloadEvent} = await import(`${root}/adapters/presenters/playlist-download-presenter.js`);
  const {playlistDownloadQuery} = await import(`${root}/adapters/gateways/playlist-download-query.js`);
  const addresses = [];
  const explorerApi = {downloadPlaylist: async recipe => {
    addresses.push(playlistDownloadQuery(recipe));
    return {filename: 'a.m3u', contents: '', contentType: 'audio/x-mpegurl', warning: ''};
  }};
  let view;
  const eventBus = {publish: event => view.show(presentPlaylistDownloadEvent(event)), subscribe() {}};
  const playlistDraft = createInMemorySession({draft: EMPTY_PLAYLIST_DRAFT});
  const playlistDownload = createPlaylistDownload({explorerApi, playlistFile: {save() {}}, playlistDraft, eventBus});
  const controller = playlistDownloadController({playlistDownload, currentTrackId: () => 'start', rejectInput() {}});
  view = playlistDownloadView({onControlsEdited: controller.controlsEdited, onDownloadRequested: controller.downloadRequested,
    onArcAdded: controller.arcAdded, onArcRemoved: controller.arcRemoved, onArcMoved: controller.arcMoved,
    onArcEdited: controller.arcEdited});
  const panel = fakeElement('section');
  view.mount(panel, playlistControlsViewModel({draft: playlistDownload.draft(), downloadState: 'idle', moods: []}));
  const byId = id => descendants(panel).find(node => node.id === id);

  byId('m3u-arc-unit').value = 'minutes';
  byId('m3u-arc-unit').onchange();
  byId('m3u-add-arc').onclick();
  byId('m3u-add-arc').onclick();
  byId('m3u-arc-length-0').value = '20';
  byId('m3u-arc-length-0').onchange();
  byId('m3u-arc-shape-1').value = 'peak';
  byId('m3u-arc-length-1').value = '15';
  byId('m3u-arc-length-1').onchange();
  assert.deepEqual([byId('m3u-count').disabled, byId('m3u-arc-length-1').placeholder], [true, 'minutes']);
  byId('m3u-bpm-min').value = '120';
  byId('m3u-bpm-max').value = '128';
  await byId('download-m3u').onclick();

  assert.deepEqual(addresses, ['/api/playlists/m3u?start=start&bpm_min=120&bpm_max=128&min_key_strength=0.5'
    + '&arc=rise&arc=peak&arc_minutes=20&arc_minutes=15']);
});

test('a loaded draft replaces every control value, harmonic mixing as a tick (#139)', () => {
  const {view, byId} = mounted();
  const values = {...VALUES, bpmMin: '118', bpmMax: '126', count: '12', harmonicMixing: false, minimumKeyStrength: '0.7',
    arcLengthUnit: 'minutes', moodHold: 'happy'};
  view.show({values});
  assert.deepEqual(['m3u-bpm-min', 'm3u-bpm-max', 'm3u-count', 'm3u-min-key-strength', 'm3u-arc-unit', 'm3u-mood']
    .map(id => byId(id).value), ['118', '126', '12', '0.7', 'minutes', 'happy']);
  assert.equal(byId('m3u-harmonic').checked, false);
});

test('#234: the controls are steps of an accordion, Tempo and length and Energy plan, open to start', () => {
  const {byId} = mounted();
  const steps = byId('m3u-download-controls').children.filter(node => node.tagName === 'DETAILS');
  assert.deepEqual(steps.map(step => [step.id, step.open, step.children[0].tagName, step.children[0].textContent]),
    [['playlist-step-tempo', true, 'SUMMARY', 'Tempo and length'], ['playlist-step-energy', true, 'SUMMARY', 'Energy plan']]);
  assert.ok(descendants(steps[0]).some(node => node.id === 'm3u-bpm-min'));
  assert.ok(descendants(steps[1]).some(node => node.id === 'm3u-add-arc'));
  assert.ok(descendants(steps[1]).some(node => node.id === 'm3u-mood'));
});

test('#234: Download M3U and its status go where the page puts them', () => {
  const heard = [];
  const view = playlistDownloadView({onControlsEdited() {}, onDownloadRequested: values => heard.push(values),
    onArcAdded() {}, onArcRemoved() {}, onArcMoved() {}, onArcEdited() {}});
  const [panel, finish] = [fakeElement('section'), fakeElement('section')];
  view.mount(panel, viewModel(), finish);
  assert.deepEqual(descendants(finish).filter(node => node.id).map(node => node.id), ['download-m3u', 'm3u-download-status']);
  assert.ok(!descendants(panel).some(node => node.id === 'download-m3u'));
});

test('#234: each arc is a collapsible row summed up in one line; a new arc opens and the others keep their state', () => {
  const {view, byId} = mounted({arcs: [{...ARC, summary: 'Arc 1 · Rising energy · length not set · default energy range'}]});
  const first = byId('m3u-arc-0');
  assert.equal(first.tagName, 'DETAILS');
  assert.deepEqual([first.children[0].tagName, first.children[0].textContent],
    ['SUMMARY', 'Arc 1 · Rising energy · length not set · default energy range']);
  first.open = false;
  view.show({arcs: [{...ARC, summary: 'Arc 1 · Rising energy · 8 tracks · default energy range'}, {...ARC, summary: 'Arc 2'}],
    arcLengthUnit: 'tracks'});
  assert.deepEqual([byId('m3u-arc-0').open, byId('m3u-arc-1').open], [false, true]);
  assert.equal(byId('m3u-arc-0').children[0].textContent, 'Arc 1 · Rising energy · 8 tracks · default energy range');
  const length = byId('m3u-arc-length-0');
  assert.equal(descendants(byId('m3u-arc-0')).find(node => node.tagName === 'LABEL' && node.htmlFor === length.id)?.textContent, 'Length');
});

test('the BPM range is marked required, a missing control is flagged, and edits are reported as you type (#234)', () => {
  const {view, heard, byId, text} = mounted();
  for (const id of ['m3u-bpm-min', 'm3u-bpm-max']) {
    assert.equal(byId(id).required, true);
    assert.equal(byId(id).getAttribute('aria-required'), 'true');
  }
  assert.match(text(), /BPM range \(required\)/);
  view.show({missing: ['bpmMax', 'length']});
  assert.deepEqual(['m3u-bpm-min', 'm3u-bpm-max', 'm3u-count', 'm3u-duration'].map(id => byId(id).getAttribute('aria-invalid')),
    ['false', 'true', 'true', 'true']);
  view.show({missing: []});
  assert.equal(byId('m3u-bpm-max').getAttribute('aria-invalid'), 'false');
  byId('m3u-bpm-min').value = '12';
  byId('m3u-bpm-min').oninput();
  assert.deepEqual(heard.edited, [{...VALUES, bpmMin: '12'}]);
});

test("the arc unit shown follows the draft's, so a duration switches it to minutes (#256)", () => {
  const {view, byId} = mounted({arcs: [ARC]});
  view.show({arcs: [ARC], arcLengthUnit: 'minutes'});
  assert.deepEqual([byId('m3u-arc-unit').value, byId('m3u-arc-length-0').placeholder], ['minutes', 'minutes']);
});

test("the arc editor shows the library's arousal range once the graph has loaded (#265)", () => {
  const {view, byId} = mounted();
  assert.equal(byId('m3u-arousal-range').textContent, 'Library arousal: not known until the graph has placed tracks with arousal.');
  view.show({arousalRange: 'Library arousal: 3.1 to 6.8'});
  assert.equal(byId('m3u-arousal-range').textContent, 'Library arousal: 3.1 to 6.8');
});
