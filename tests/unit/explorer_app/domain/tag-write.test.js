// Issue #132: the page's tag-write action, previewed before it can be applied.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {TAG_WRITE_STATES, TagWriteTransitionError, nextTagWriteState} from '../../../../music_explorer/frameworks/explorer/assets/app/domain/tag-write.js';

const LEGAL = {
  idle: {preview: 'previewing'},
  previewing: {succeed: 'previewed', fail: 'failed'},
  previewed: {preview: 'previewing', apply: 'applying', discard: 'idle'},
  applying: {succeed: 'applied', fail: 'failed'},
  applied: {preview: 'previewing'},
  failed: {preview: 'previewing'},
};

test('only a previewed action can be applied, and every transition is in the table', () => {
  assert.deepEqual(TAG_WRITE_STATES, Object.keys(LEGAL));
  for (const state of TAG_WRITE_STATES) {
    for (const action of ['preview', 'apply', 'succeed', 'fail', 'discard']) {
      const next = LEGAL[state][action];
      if (next) assert.equal(nextTagWriteState(state, action), next);
      else assert.throws(() => nextTagWriteState(state, action), TagWriteTransitionError);
    }
  }
});

test('an illegal transition names the action and the state', () => {
  assert.throws(() => nextTagWriteState('idle', 'apply'), /cannot apply while idle/);
});
