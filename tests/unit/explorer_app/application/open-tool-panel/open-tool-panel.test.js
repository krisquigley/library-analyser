// Issue #233: the header's buttons open and close the tool panels; every change is an event the views follow.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createToolPanels} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/open-tool-panel/open-tool-panel.js';
import {TOOL_PANEL_EVENT_TYPES} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/open-tool-panel/tool-panel-events.js';

function harness() {
  const published = [];
  const toolPanels = createToolPanels({eventBus: {publish: event => published.push(event), subscribe() {}}});
  return {toolPanels, published};
}

test('the event types are the ones the use case publishes', () => {
  assert.deepEqual(TOOL_PANEL_EVENT_TYPES, ['tool-panel-opened', 'tool-panel-closed']);
});

test('toggling a closed panel opens it, and toggling it again closes it', () => {
  const {toolPanels, published} = harness();
  toolPanels.toggle('library');
  assert.equal(toolPanels.isOpen('library'), true);
  toolPanels.toggle('library');
  assert.deepEqual(published, [{type: 'tool-panel-opened', tool: 'library', presentation: 'drawer'},
    {type: 'tool-panel-closed', tool: 'library'}]);
  assert.equal(toolPanels.isOpen('library'), false);
});

test('one modal at a time: opening Write tags closes the playlist generator, and the Library drawer stays open', () => {
  const {toolPanels, published} = harness();
  toolPanels.toggle('library');
  toolPanels.toggle('playlist');
  toolPanels.toggle('tag-write');
  assert.deepEqual(published.slice(1), [{type: 'tool-panel-opened', tool: 'playlist', presentation: 'modal'},
    {type: 'tool-panel-closed', tool: 'playlist'}, {type: 'tool-panel-opened', tool: 'tag-write', presentation: 'modal'}]);
  assert.equal(toolPanels.isOpen('library'), true);
});

test('closing a panel that is already closed is rejected, and an unknown tool is rejected', () => {
  const {toolPanels, published} = harness();
  assert.throws(() => toolPanels.close('playlist'), /cannot close while closed/);
  assert.throws(() => toolPanels.toggle('settings'), /no tool panel called settings/i);
  assert.deepEqual(published, []);
});

test('the graph filters take the Library drawer\'s place beside the graph', () => {
  const {toolPanels, published} = harness();
  toolPanels.toggle('library');
  toolPanels.toggle('filters');
  assert.deepEqual(published.slice(1), [{type: 'tool-panel-closed', tool: 'library'},
    {type: 'tool-panel-opened', tool: 'filters', presentation: 'drawer'}]);
});

test('a panel asked open stays open, and opening it again changes nothing (#236)', () => {
  const {toolPanels, published} = harness();
  toolPanels.open('tag-write');
  toolPanels.open('tag-write');
  assert.equal(toolPanels.isOpen('tag-write'), true);
  assert.deepEqual(published, [{type: 'tool-panel-opened', tool: 'tag-write', presentation: 'modal'}]);
});
