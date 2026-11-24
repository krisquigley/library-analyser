// Issue #233: the header's tools open as panels over the graph: the Library as a drawer, the others as centred modals.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {TOOL_PANELS, TOOL_PANEL_STATES, ToolPanelTransitionError, isToolPanel, nextToolPanelState, modalsDisplacedBy} from '../../../../music_explorer/frameworks/explorer/assets/app/domain/tool-panels.js';

test('a panel opens only when closed and closes only when open', () => {
  assert.deepEqual(TOOL_PANEL_STATES, ['closed', 'open']);
  assert.equal(nextToolPanelState('closed', 'open'), 'open');
  assert.equal(nextToolPanelState('open', 'close'), 'closed');
  assert.throws(() => nextToolPanelState('open', 'open'), ToolPanelTransitionError);
  assert.throws(() => nextToolPanelState('closed', 'close'), ToolPanelTransitionError);
});

test('the Library is a drawer beside the graph; the playlist generator and Write tags are modals', () => {
  assert.deepEqual(TOOL_PANELS, {library: 'drawer', playlist: 'modal', 'tag-write': 'modal'});
  assert.equal(isToolPanel('playlist'), true);
  assert.equal(isToolPanel('constructor'), false);
  assert.equal(isToolPanel('settings'), false);
});

test('opening a modal displaces any other open modal, never the drawer', () => {
  assert.deepEqual(modalsDisplacedBy('tag-write', ['library', 'playlist']), ['playlist']);
  assert.deepEqual(modalsDisplacedBy('playlist', ['library']), []);
  assert.deepEqual(modalsDisplacedBy('library', ['playlist']), []);
});
