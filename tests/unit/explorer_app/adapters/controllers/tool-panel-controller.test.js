// Issue #233: the header and the panels' close controls, checked before the use case sees them.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {toolPanelController} from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/controllers/tool-panel-controller.js';

function harness(open = []) {
  const calls = [], rejected = [];
  const toolPanels = {toggle: tool => calls.push(['toggle', tool]), open: tool => calls.push(['open', tool]),
    close: tool => calls.push(['close', tool]), isOpen: tool => open.includes(tool)};
  return {controller: toolPanelController({toolPanels, rejectInput: message => rejected.push(message)}), calls, rejected};
}

test('a header button toggles its tool', () => {
  const {controller, calls} = harness();
  controller.toggleRequested('playlist');
  assert.deepEqual(calls, [['toggle', 'playlist']]);
});

test('a close request closes an open panel and ignores one the page has already closed', () => {
  const {controller, calls} = harness(['tag-write']);
  controller.closeRequested('tag-write');
  controller.closeRequested('playlist');
  assert.deepEqual(calls, [['close', 'tag-write']]);
});

test('an unknown tool is rejected with a message', () => {
  const {controller, calls, rejected} = harness();
  controller.toggleRequested('settings');
  controller.closeRequested(undefined);
  assert.deepEqual(calls, []);
  assert.deepEqual(rejected, ['There is no tool called settings', 'There is no tool called undefined']);
});

test('a shortcut opens its tool, and an unknown one is rejected (#236)', () => {
  const {controller, calls, rejected} = harness();
  controller.openRequested('tag-write');
  controller.openRequested('settings');
  assert.deepEqual(calls, [['open', 'tag-write']]);
  assert.deepEqual(rejected, ['There is no tool called settings']);
});
