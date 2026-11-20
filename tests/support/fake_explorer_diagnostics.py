"""A stand-in for the Explorer page's opt-in diagnostics seam (#146), for the timing tools' Node tests.

It has the seam's shape: subscribe and observe by event type, a snapshot, the scene and the views. A test
publishes the page's events through it, in the order the page would, instead of calling page functions.
"""

FAKE_EXPLORER_DIAGNOSTICS = r'''
function fakeExplorerDiagnostics({snapshot = () => ({}), scene = () => ({}), views = () => ({})} = {}) {
  const subscribers = new Map(), observers = new Map();
  const listOf = (map, type) => map.get(type) ?? map.set(type, []).get(type);
  const removing = (list, item) => () => { const at = list.indexOf(item); if (at >= 0) list.splice(at, 1); };
  return {
    subscribe(type, handler) { const list = listOf(subscribers, type); list.push(handler); return removing(list, handler); },
    observe(type, observer) { const list = listOf(observers, type); list.push(observer); return removing(list, observer); },
    publish(event, pageHandler = () => {}) {
      for (const observer of [...listOf(observers, event.type)]) observer.before?.(event);
      pageHandler(event);
      for (const handler of [...listOf(subscribers, event.type)]) handler(event);
      for (const observer of [...listOf(observers, event.type)]) observer.after?.(event);
    },
    snapshot: () => Object.freeze({...snapshot()}),
    scene,
    views,
  };
}
'''
