"""Delayed pre-reset POST responses must not roll back the tab's epoch.

Reuse the transferred deferred-request fixture without altering its original red
contracts. This covers response delivery order, not server POST evaluation order.
"""
import subprocess
import unittest
from pathlib import Path

from tests.acceptance.test_explorer_selection_detail_races import (
    ASSETS, HARNESS, NODE, ROOT,
)

PRE_RESET_POST = r"""
const a=select('A');
const original=req('/api/current').body;
assert.equal(original.selection_epoch,7,'fixture begins in the pre-reset epoch');
// A was evaluated before reset, but its response remains in flight.
await history('/api/reset',null,8,[]);
await accept('A',0,7,['PRE_RESET'],true);
assert((await a).ok);
assert.equal(context.getStateForTesting().current_track_id,null,
  'late pre-reset POST must not replace reset selection');
assert.deepEqual(Array.from(context.getStateForTesting().history),[],
  'late pre-reset POST must not restore pre-reset history');
assert.equal(text(),'','reset detail remains empty');
assert.deepEqual(ids(),[],'stale POST cannot authorize detail');
const b=select('B');
const next=req('/api/current',1).body;
assert.equal(next.selection_epoch,8,
  'late pre-reset POST must not roll back the epoch sent with the next selection');
assert.equal(next.selection_token,original.selection_token+1,
  'reset must preserve monotonic per-tab selection tokens');
assert.equal(next.selection_client_id,original.selection_client_id,
  'reset must preserve per-tab client identity');
await accept('B',1,8,[]);
await finish('B');
assert((await b).ok);
assert.equal(context.getStateForTesting().current_track_id,'B');
assert.deepEqual(ids(),['/api/tracks/B']);
assert(text().includes('DETAIL B'));
"""


REFRESH_DURING_ACCEPTED_DETAIL = r"""
const a=select('A');
await accept('A');
assert.deepEqual(ids(),['/api/tracks/A'],'accepted selection owns its pending detail GET');
const refresh=settled(context.refresh());
await nextRefreshFrame();
req('/api/state').ok(snapshot('A',7,[]));
await flush();
assert.deepEqual(ids(),['/api/tracks/A'],
  'refresh must not duplicate the accepted selection detail GET already in flight');
await finish('A');
assert((await a).ok);
assert((await refresh).ok);
assert.equal(context.getStateForTesting().current_track_id,'A');
assert(text().includes('DETAIL A'));
"""


REFRESH_DURING_HISTORY_POST = r"""
await paintInitial();
const undo=settled(context.applyHistorySelection('/api/undo'));
assert(loading(),'history intent immediately owns detail loading');
const refresh=settled(context.refresh());
await nextRefreshFrame();
req('/api/state').ok(snapshot('OLD',7,[]));
await flush();
assert.deepEqual(ids(),['/api/tracks/OLD'],
  'refresh during pending history POST must not fetch pre-history detail');
assert(loading(),'pending history retains scoped loading through refresh');
assert(!text().includes('DETAIL OLD'),'pending history cannot restore ghost old detail');
assert((await refresh).ok);
req('/api/undo').ok(snapshot('PRIOR',8,['ROOT']));
await nextRefreshFrame();
req('/api/state',1).ok(snapshot('PRIOR',8,['ROOT']));
await flush();
await finish('PRIOR');
assert((await undo).ok);
assert.equal(context.getStateForTesting().current_track_id,'PRIOR');
assert(text().includes('DETAIL PRIOR'));
assert(!loading());
"""

REFRESH_AFTER_FAILED_POST = r"""
await paintInitial();
const a=select('A');
req('/api/current',1).fail('Current selection failed');
await a;await flush();
assert(errorVisible(),'failed POST exposes scoped error');
assert.deepEqual(ids(),['/api/tracks/OLD'],'failed intent never authorizes A detail');
const refresh=settled(context.refresh());
await nextRefreshFrame();
req('/api/state').ok(snapshot('OLD',8,[]));
await flush();
assert.equal(context.getStateForTesting().current_track_id,'OLD',
  'explicit refresh after settled POST failure reconciles authoritative selection');
assert.deepEqual(ids(),['/api/tracks/OLD','/api/tracks/OLD'],
  'authoritative refresh can recover accepted detail after failed intent');
await finish('OLD',1);
assert((await refresh).ok);
assert(text().includes('DETAIL OLD'));assert(!errorVisible());assert(!loading());
const b=select('B');
assert.equal(req('/api/current',2).body.selection_epoch,8,
  'authoritative recovery refresh synchronizes the current epoch');
await accept('B',2,8);await finish('B');assert((await b).ok);
"""


class SelectionDetailEpochTests(unittest.TestCase):
    def test_pre_reset_post_cannot_roll_back_next_selection_epoch(self):
        self.run_scenario(PRE_RESET_POST)

    def test_refresh_does_not_duplicate_pending_accepted_detail(self):
        self.run_scenario(REFRESH_DURING_ACCEPTED_DETAIL)

    def test_refresh_during_history_post_preserves_history_intent(self):
        self.run_scenario(REFRESH_DURING_HISTORY_POST)

    def test_refresh_after_failed_post_recovers_authoritative_selection(self):
        self.run_scenario(REFRESH_AFTER_FAILED_POST)

    def run_scenario(self, scenario):
        self.assertTrue(Path(NODE).is_file(), f'Node prerequisite unavailable: {NODE}')
        for asset in ASSETS:
            with self.subTest(asset=str(asset.relative_to(ROOT))):
                script = (HARNESS + '\n(async()=>{\n' + scenario
                          + '\n})().catch(e=>{console.error(e);process.exitCode=1;});')
                result = subprocess.run(
                    [NODE, '-e', script, str(asset)], capture_output=True,
                    text=True, timeout=15, cwd=ROOT,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
