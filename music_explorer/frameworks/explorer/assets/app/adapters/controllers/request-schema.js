// Validates a request against the schema its use case declares (#146).
// A request is rejected whole, with a message the listener can act on; nothing is coerced.

export class RequestSchemaError extends Error {}

const FIELD_CHECKS = Object.freeze({
  'number-text': (value, field) => (typeof value === 'string' && isBlankOrFinite(value)) || `${field.label} must be a number`,
  switch: (value, field) => typeof value === 'boolean' || `${field.label} must be on or off`,
  choice: (value, field) => field.choices.includes(value) || `${field.label} must be one of: ${field.choices.join(', ')}`,
  text: (value, field) => typeof value === 'string' || `${field.label} must be text`,
  'text-list': (value, field) => (Array.isArray(value) && value.every(item => typeof item === 'string'))
    || `${field.label} must be a list of text`,
});

export function validRequest(schema, request) {
  for (const [name, value] of Object.entries(request)) {
    if (!Object.hasOwn(schema.fields, name)) throw new RequestSchemaError(`Unknown ${schema.subject}: ${name}`);
    const field = schema.fields[name];
    const verdict = FIELD_CHECKS[field.kind](value, field);
    if (verdict !== true) throw new RequestSchemaError(verdict);
  }
  return Object.freeze({...request});
}

function isBlankOrFinite(text) {
  const trimmed = text.trim();
  return trimmed === '' || Number.isFinite(Number(trimmed));
}
