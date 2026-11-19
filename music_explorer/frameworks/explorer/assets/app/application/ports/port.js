// A port names the operations a use case needs from an outer adapter (#146).

export function requirePort(port, adapter) {
  const missing = port.operations.find(operation => typeof adapter?.[operation] !== 'function');
  if (missing) throw new TypeError(`${port.name} needs ${missing}`);
  return adapter;
}
