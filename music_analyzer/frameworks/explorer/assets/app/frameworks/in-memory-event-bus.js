// The EventBus port, carried in memory within the page (#146).

export function createInMemoryEventBus() {
  const handlersByType = new Map();
  return Object.freeze({
    publish(event) {
      for (const handler of [...(handlersByType.get(event.type) || [])]) handler(event);
    },
    subscribe(type, handler) {
      if (!handlersByType.has(type)) handlersByType.set(type, []);
      handlersByType.get(type).push(handler);
      return () => {
        const handlers = handlersByType.get(type);
        handlers.splice(handlers.indexOf(handler), 1);
      };
    },
  });
}
