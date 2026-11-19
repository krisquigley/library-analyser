// Carries events from the use cases to whatever reacts to them (#146).
// publish(event) delivers an event ({type, …}); subscribe(type, handler) returns an unsubscribe function.

export const EVENT_BUS = Object.freeze({name: 'EventBus', operations: Object.freeze(['publish', 'subscribe'])});
