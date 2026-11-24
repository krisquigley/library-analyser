// Issue #233: tool panel events become what the header and the panels show.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {toolPanelViewModel} from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/presenters/tool-panel-presenter.js';

test('an opened modal and a closed drawer', () => {
  assert.deepEqual(toolPanelViewModel({type: 'tool-panel-opened', tool: 'playlist', presentation: 'modal'}),
    {tool: 'playlist', open: true, modal: true});
  assert.deepEqual(toolPanelViewModel({type: 'tool-panel-closed', tool: 'library'}), {tool: 'library', open: false, modal: false});
});
