// The opt-in diagnostics seam (#146, owner decision A): what the #86 timing tools and the composition tests
// observe, in place of reaching into the page's variables. It is off unless the page address has `diagnostics`.
// Events are heard through the page's own buses; the state is a frozen copy; the scene is handed over live,
// because the timing tools measure the renderer itself. Nothing here can change the page.

export function diagnosticsRequested(search) {
  return new URLSearchParams(search).has('diagnostics');
}

export function createExplorerDiagnostics({buses, snapshot, scene}) {
  const busByType = new Map();
  for (const [types, bus] of buses) {
    for (const type of types) {
      if (busByType.has(type)) throw new Error(`Two buses carry the event ${type}`);
      busByType.set(type, bus);
    }
  }
  return Object.freeze({
    eventTypes: () => [...busByType.keys()],
    subscribe(type, handler) {
      if (!busByType.has(type)) throw new Error(`No diagnostics event: ${type}`);
      return busByType.get(type).subscribe(type, handler);
    },
    snapshot: () => frozenCopy(snapshot()),
    scene,
  });
}

export function installExplorerDiagnostics(page, search, options) {
  if (!diagnosticsRequested(search)) return null;
  const diagnostics = createExplorerDiagnostics(options);
  Object.defineProperty(page, 'explorerDiagnostics', {value: diagnostics, enumerable: false, writable: false});
  return diagnostics;
}

function frozenCopy(value) {
  if (value === null || typeof value !== 'object') return value;
  const copy = Array.isArray(value) ? value.map(frozenCopy)
    : Object.fromEntries(Object.entries(value).map(([key, item]) => [key, frozenCopy(item)]));
  return Object.freeze(copy);
}
