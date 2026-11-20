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

test('a dispatch can be observed just before and just after its subscribers run, until the observer stops', () => {
  const bus = createInMemoryEventBus();
  const heard = [];
  bus.subscribe('graph-render-due', () => heard.push('subscriber'));
  const stop = bus.observeDispatch('graph-render-due', {
    before: event => heard.push(['before', event.type]), after: event => heard.push(['after', event.type])});
  bus.observeDispatch('graph-render-due', {after: () => heard.push('second observer after')});
  bus.publish({type: 'graph-render-due'});
  stop();
  bus.publish({type: 'graph-render-due'});
  assert.deepEqual(heard, [['before', 'graph-render-due'], 'subscriber', ['after', 'graph-render-due'],
    'second observer after', 'subscriber', 'second observer after']);
});

test('an observed dispatch whose subscriber throws still reports the throw to the publisher', () => {
  const bus = createInMemoryEventBus();
  const heard = [];
  bus.subscribe('graph-ready', () => { throw new Error('view failed'); });
  bus.observeDispatch('graph-ready', {before: () => heard.push('before'), after: () => heard.push('after')});
  assert.throws(() => bus.publish({type: 'graph-ready'}), /view failed/);
  assert.deepEqual(heard, ['before']);
});
