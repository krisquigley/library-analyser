"""Issue #146 (owner decision A): the real Explorer page offers its diagnostics seam only when the address asks."""
import unittest

from tests.support.explorer_detail_harness import ASSETS
from tests.support.node_script import run_node_script

SCRIPT = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function page(search) {
  const context = vm.createContext({console, URLSearchParams, setTimeout, clearTimeout, requestAnimationFrame() {},
    sessionStorage: {getItem: () => null, setItem() {}}, fetch: () => new Promise(() => {}),
    ...(search === null ? {} : {location: {search}})});
  vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
  return context;
}

for (const search of [null, '', '?track=a']) {
  assert.equal(page(search).explorerDiagnostics, undefined, `no seam for ${JSON.stringify(search)}`);
}

const context = page('?diagnostics');
const diagnostics = context.explorerDiagnostics;
assert.deepEqual(JSON.parse(JSON.stringify(diagnostics.snapshot())), {
  currentTrackId: null, selectionEpoch: null, history: [], graphStatus: 'idle', cameraFocusActive: false, pendingCameraTrackId: null,
  selectionPending: false, trackSearchStatus: 'idle', trackResultCount: 0});
for (const type of ['track-chosen', 'selection-accepted', 'camera-focus-started', 'camera-focus-cancelled',
  'camera-focus-finished', 'graph-ready', 'graph-rendering-paused', 'track-page-loaded', 'playlist-downloaded']) {
  assert.ok(diagnostics.eventTypes().includes(type), type);
}
const timed = [];
const stop = diagnostics.observe('graph-model-building', {before: () => timed.push('before'), after: () => timed.push('after')});
assert.equal(typeof stop, 'function');
for (const type of ['graph-model-building', 'graph-model-built']) assert.ok(diagnostics.eventTypes().includes(type), type);
assert.deepEqual(Object.keys(diagnostics.scene()).sort(), ['findSceneObject', 'graph', 'graphData', 'graphObjectTrackId', 'halo']);
assert.deepEqual(Object.keys(diagnostics.views()).sort(), ['detailField', 'trackDetailFields', 'trackMetadata']);
assert.deepEqual(Object.keys(diagnostics.graph()).sort(), ['layout', 'model', 'visible']);
assert.ok(Object.isFrozen(diagnostics.graph().model));
vm.runInContext('explorerDiagnostics = null', context);
assert.equal(context.explorerDiagnostics, diagnostics, 'the page cannot replace its seam');
assert.ok(!Object.keys(context).includes('explorerDiagnostics'), 'the seam is not enumerable');

// Tests and tools observe the page only through this seam: the page offers no module exports and no test hooks.
const module = {exports: {}};
const loaded = vm.createContext({console, URLSearchParams, setTimeout, clearTimeout, requestAnimationFrame() {}, module,
  sessionStorage: {getItem: () => null, setItem() {}}, fetch: () => new Promise(() => {}), location: {search: '?diagnostics'}});
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), loaded);
assert.deepEqual(Object.keys(module.exports), [], 'the page exports nothing');
const hooks = [...vm.runInContext('Object.getOwnPropertyNames(globalThis)', loaded)].filter(name => /ForTesting$/.test(name));
assert.deepEqual(hooks, [], 'the page declares no test hooks');
console.log('NODE_SCRIPT_COMPLETED');
"""


class ExplorerDiagnosticsSeamTests(unittest.TestCase):
    def test_the_seam_is_present_and_read_only_only_with_the_diagnostics_flag(self):
        for asset in ASSETS:
            with self.subTest(asset=str(asset)):
                run_node_script(self, SCRIPT, str(asset))


if __name__ == '__main__':
    unittest.main()
