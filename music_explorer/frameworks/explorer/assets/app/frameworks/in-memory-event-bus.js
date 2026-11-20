// The EventBus port, carried in memory within the page (#146).
// observeDispatch is for the diagnostics seam only: it times an event's handling from just before its
// subscribers run to just after. It is not part of the port, and no use case or view relies on it.

export function createInMemoryEventBus() {
  const handlersByType = new Map();
  const observersByType = new Map();

  function register(registry, type, entry) {
    if (!registry.has(type)) registry.set(type, []);
    registry.get(type).push(entry);
    return () => {
      const entries = registry.get(type);
      entries.splice(entries.indexOf(entry), 1);
    };
  }

  return Object.freeze({
    publish(event) {
      const observers = [...(observersByType.get(event.type) || [])];
      for (const observer of observers) observer.before?.(event);
      for (const handler of [...(handlersByType.get(event.type) || [])]) handler(event);
      for (const observer of observers) observer.after?.(event);
    },
    subscribe: (type, handler) => register(handlersByType, type, handler),
    observeDispatch: (type, observer) => register(observersByType, type, observer),
  });
}
