// Issue #146: a use case's session, kept in memory within the page.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createInMemorySession} from '../../../../music_explorer/frameworks/explorer/assets/app/frameworks/in-memory-session.js';

test('a session starts as given and replaces only the fields it is given', () => {
  const session = createInMemorySession({loadState: 'idle', model: 'empty'});
  assert.deepEqual(session.read(), {loadState: 'idle', model: 'empty'});
  session.write({loadState: 'loading'});
  assert.deepEqual(session.read(), {loadState: 'loading', model: 'empty'});
});

test('what a reader holds never changes under it', () => {
  const session = createInMemorySession({loadState: 'idle'});
  const before = session.read();
  session.write({loadState: 'ready'});
  assert.equal(before.loadState, 'idle');
  assert.ok(Object.isFrozen(session.read()));
});
