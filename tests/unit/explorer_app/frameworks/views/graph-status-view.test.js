// Issue #146: the library graph's status panel on screen.
import {test, beforeEach} from 'node:test';
import assert from 'node:assert/strict';
import {graphStatusView} from '../../../../../music_explorer/frameworks/explorer/assets/app/frameworks/views/graph-status-view.js';
import {byTag, descendants, installFakeDocument} from '../fake-document.js';

let roots;
beforeEach(() => { roots = installFakeDocument(['graph-load-status']); });

function watching() {
  const heard = {reloads: 0, playlistControls: 0};
  const view = graphStatusView({onReload: () => { heard.reloads++; },
    appendPlaylistControls: panel => { heard.playlistControls++; panel.append(Object.assign(document.createElement('div'), {id: 'm3u'})); }});
  return {view, heard, panel: roots['graph-load-status']};
}

const buttons = panel => byTag(panel, 'button');

test('while the graph loads it says so politely, and offers no button to load it by hand', () => {
  const {view, panel} = watching();
  view.show({status: 'loading', message: 'Loading the library graph.'});
  const busy = descendants(panel).find(node => node.textContent === 'Loading graph…');
  assert.deepEqual([busy.getAttribute('role'), busy.getAttribute('aria-live')], ['status', 'polite']);
  assert.deepEqual(buttons(panel), []);
  view.show({status: 'rendering', message: 'Drawing.'});
  assert.ok(descendants(panel).some(node => node.textContent === 'Rendering graph…'));
});

test('a failed graph is an alert with a Retry graph button, and focus stays where the listener left it', () => {
  const {view, heard, panel} = watching();
  view.show({status: 'error', message: 'Unable to load graph: busy'});
  const alert = descendants(panel).find(node => node.textContent === 'Unable to load graph: busy');
  assert.deepEqual([alert.getAttribute('role'), alert.getAttribute('aria-live')], ['alert', 'assertive']);
  const [retry] = buttons(panel);
  assert.deepEqual([retry.id, retry.type, retry.textContent], ['retry-graph', 'button', 'Retry graph']);
  retry.onclick();
  assert.equal(heard.reloads, 1);
  assert.ok(!descendants(panel).some(node => node.focused));
});

test('a ready graph says so, offers Reload graph and the playlist controls', () => {
  const {view, heard, panel} = watching();
  view.show({status: 'ready', message: 'Graph ready: 12 tracks.'});
  assert.deepEqual(panel.children.map(node => node.textContent || node.id),
    ['Library graph', 'Graph ready: 12 tracks.', 'Reload graph', 'm3u']);
  assert.equal(buttons(panel)[0].id, 'reload-graph');
  assert.equal(heard.playlistControls, 1);
});

test('a new message for a graph that stays ready keeps the live playlist controls', () => {
  const {view, heard, panel} = watching();
  view.show({status: 'ready', message: 'Graph ready: 12 tracks.'});
  const controls = panel.children[3];
  view.show({status: 'ready', message: 'Graph ready: 5 of 12 tracks shown.'});
  assert.equal(panel.children[1].textContent, 'Graph ready: 5 of 12 tracks shown.');
  assert.equal(panel.children[3], controls);
  assert.equal(heard.playlistControls, 1);
});

test('titles and messages are text, never markup', () => {
  const {view, panel} = watching();
  view.show({status: 'error', message: '<img src=x onerror=alert(1)>'});
  assert.ok(!descendants(panel).some(node => node.tagName === 'IMG'));
  assert.equal(panel.children[1].textContent, '<img src=x onerror=alert(1)>');
});
