// Issue #146: selection tickets kept for the tab in sessionStorage.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {sessionSelectionTickets} from '../../../../music_explorer/frameworks/explorer/assets/app/frameworks/session-selection-tickets.js';
import {SELECTION_TICKETS} from '../../../../music_explorer/frameworks/explorer/assets/app/application/ports/selection-tickets.js';
import {requirePort} from '../../../../music_explorer/frameworks/explorer/assets/app/application/ports/port.js';

function memoryStorage(entries = {}) {
  const data = new Map(Object.entries(entries));
  return {data, getItem: key => data.get(key) ?? null, setItem: (key, value) => data.set(key, String(value))};
}
const clock = {now: () => 36 ** 3, random: () => 0.5};

test('tickets implement the SelectionTickets port', () => {
  assert.ok(requirePort(SELECTION_TICKETS, sessionSelectionTickets({storage: memoryStorage(), ...clock})));
});

test('tickets count on from the last one the tab issued, and store each', () => {
  const storage = memoryStorage({'music-explorer-selection-post-seq': '4'});
  const tickets = sessionSelectionTickets({storage, ...clock});
  assert.deepEqual([tickets.nextTicket(), tickets.nextTicket()], [5, 6]);
  assert.equal(storage.data.get('music-explorer-selection-post-seq'), '6');
});

test('an unreadable stored ticket starts again from one', () => {
  for (const stored of ['x', '-3', '0']) {
    const tickets = sessionSelectionTickets({storage: memoryStorage({'music-explorer-selection-post-seq': stored}), ...clock});
    assert.equal(tickets.nextTicket(), 1, stored);
  }
});

test('the tab keeps one client id, made once and stored', () => {
  const storage = memoryStorage();
  const tickets = sessionSelectionTickets({storage, ...clock});
  assert.equal(tickets.clientId(), 'tab-1000-i');
  assert.equal(sessionSelectionTickets({storage, now: () => 0, random: () => 0.25}).clientId(), 'tab-1000-i');
});

test('without usable storage, tickets still count and the client id still holds for the page', () => {
  const broken = {getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); }};
  for (const storage of [undefined, broken]) {
    const tickets = sessionSelectionTickets({storage, ...clock});
    assert.deepEqual([tickets.nextTicket(), tickets.nextTicket()], [1, 2]);
    assert.equal(tickets.clientId(), 'tab-i');
    assert.equal(tickets.clientId(), 'tab-i');
  }
});
