"""Deferred selection/history contracts for #70, for both packaged JS assets.

These intentionally red feedback tests do not implement the proposed UI. Passing
controls separately protect the existing POST gate and stale-response guards.
Node/fixture failures are errors, never accepted as evidence of missing feedback.
"""
from pathlib import Path
import subprocess
import unittest
from tests.support.explorer_detail_harness import ASSETS, HARNESS, NODE, ROOT


SCENARIOS = {
    "latest_intent_loading_is_immediate_before_post": r"""
await paintInitial(); const a=select('A');
assert(loading(),'#70: latest selection needs scoped loading before POST resolves');
assert(!text().includes('DETAIL OLD'),'#70: old panel must not masquerade as new selection');
""",
    "undo_replaces_pending_detail_with_history_loading": r"""
await paintInitial();const a=select('A');await accept('A',1);
const undo=settled(context.applyHistorySelection('undo'));
req('/api/undo').ok(snapshot('PRIOR',8,['ROOT']));await nextRefreshFrame();
req('/api/state').ok(snapshot('PRIOR',8,['ROOT']));await flush();await finish('A');await a;
assert(loading(),'#70: stale detail must not clear undo current-detail loading');
assert(!text().includes('DETAIL OLD'),'#70: undo must not show ghost old detail while waiting');
await finish('PRIOR');assert((await undo).ok);assert(!loading());assert(text().includes('DETAIL PRIOR'));
""",
}


class SelectionDetailRaceTests(unittest.TestCase):
    def run_scenario(self, name):
        if not Path(NODE).is_file():
            self.fail(f"Node prerequisite unavailable: {NODE}")
        for asset in ASSETS:
            with self.subTest(asset=str(asset), scenario=name):
                script = HARNESS + "\n(async()=>{\n" + SCENARIOS[name] + "\n})().catch(e=>{console.error(e);process.exitCode=1;});"
                result = subprocess.run([NODE, "-e", script, str(asset)], capture_output=True,
                                        text=True, timeout=15, cwd=ROOT)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


def _scenario_test(name):
    def test(self):
        self.run_scenario(name)
    return test


for _name in SCENARIOS:
    setattr(SelectionDetailRaceTests, "test_" + _name, _scenario_test(_name))

if __name__ == "__main__":
    unittest.main()
