// Issue #146: the EventBus port, carried in memory.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createInMemoryEventBus} from '../../../../music_explorer/frameworks/explorer/assets/app/frameworks/in-memory-event-bus.js';
import {EVENT_BUS} from '../../../../music_explorer/frameworks/explorer/assets/app/application/ports/event-bus.js';
import {requirePort} from '../../../../music_explorer/frameworks/explorer/assets/app/application/ports/port.js';

test('the bus implements the EventBus port', () => {
  const bus = createInMemoryEventBus();
  assert.equal(requirePort(EVENT_BUS, bus), bus);
});

test('an event reaches the subscribers of its type, in the order they subscribed', () => {
  const bus = createInMemoryEventBus();
  const heard = [];
  bus.subscribe('playlist-downloaded', event => heard.push(['first', event.filename]));
  bus.subscribe('playlist-downloaded', event => heard.push(['second', event.filename]));
  bus.subscribe('playlist-download-failed', () => heard.push(['other']));
  bus.publish({type: 'playlist-downloaded', filename: 'a.m3u'});
  assert.deepEqual(heard, [['first', 'a.m3u'], ['second', 'a.m3u']]);
});

test('an unsubscribed handler hears nothing more', () => {
  const bus = createInMemoryEventBus();
  const heard = [];
  const unsubscribe = bus.subscribe('playlist-download-started', event => heard.push(event.type));
  bus.publish({type: 'playlist-download-started'});
  unsubscribe();
  bus.publish({type: 'playlist-download-started'});
  assert.deepEqual(heard, ['playlist-download-started']);
});
