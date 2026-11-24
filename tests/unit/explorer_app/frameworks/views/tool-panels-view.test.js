// Issue #233: the header's buttons and the tool panels on screen.
import {test, beforeEach} from 'node:test';
import assert from 'node:assert/strict';
import {toolPanelsView} from '../../../../../music_explorer/frameworks/explorer/assets/app/frameworks/views/tool-panels-view.js';
import {installFakeDocument} from '../fake-document.js';

let roots;
beforeEach(() => {
  roots = installFakeDocument(['open-library', 'library-panel', 'open-playlist', 'playlist-panel', 'close-playlist', 'detail-write-tags']);
  for (const id of ['library-panel', 'playlist-panel']) {
    Object.assign(roots[id], {open: false, shown: [],
      show() { this.open = true; this.shown.push('show'); },
      showModal() { this.open = true; this.shown.push('showModal'); },
      close() { this.open = false; this.shown.push('close'); }});
  }
});

function mounted() {
  const heard = [];
  const view = toolPanelsView({onToggleRequested: tool => heard.push(['toggle', tool]), onCloseRequested: tool => heard.push(['close', tool]),
    onOpenRequested: tool => heard.push(['open', tool])});
  view.mount();
  return {view, heard};
}

test('a header button and a close button report their tool; tools missing from the page are skipped', () => {
  const {heard} = mounted();
  roots['open-playlist'].onclick();
  roots['close-playlist'].onclick();
  roots['open-library'].onclick();
  assert.deepEqual(heard, [['toggle', 'playlist'], ['close', 'playlist'], ['toggle', 'library']]);
});

test('Esc and a click on the backdrop ask to close a modal; the page closes it only when the use case says so', () => {
  const {heard} = mounted();
  const panel = roots['playlist-panel'];
  let prevented = false;
  panel.oncancel({preventDefault() { prevented = true; }});
  panel.onclick({target: panel});
  panel.onclick({target: {}});
  assert.equal(prevented, true);
  assert.deepEqual(heard, [['close', 'playlist'], ['close', 'playlist']]);
  assert.deepEqual(panel.shown, []);
});

test('a modal opens over the page and the drawer opens beside the graph; each header button says whether it is open', () => {
  const {view} = mounted();
  view.show({tool: 'playlist', open: true, modal: true});
  view.show({tool: 'library', open: true, modal: false});
  assert.deepEqual(roots['playlist-panel'].shown, ['showModal']);
  assert.deepEqual(roots['library-panel'].shown, ['show']);
  assert.equal(roots['open-playlist'].getAttribute('aria-expanded'), 'true');
  view.show({tool: 'playlist', open: false, modal: true});
  assert.deepEqual(roots['playlist-panel'].shown, ['showModal', 'close']);
  assert.equal(roots['open-playlist'].getAttribute('aria-expanded'), 'false');
  view.show({tool: 'tag-write', open: true, modal: true});
});

test('a click on the Library drawer itself never closes it: only a modal has a backdrop', () => {
  const {heard} = mounted();
  const drawer = roots['library-panel'];
  drawer.onclick?.({target: drawer});
  assert.deepEqual(heard, []);
});

test('the selected track card\'s Write tags button opens the tag-write dialog (#236)', () => {
  const {heard} = mounted();
  roots['detail-write-tags'].onclick();
  assert.deepEqual(heard, [['open', 'tag-write']]);
});
