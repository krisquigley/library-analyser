// Time as the use cases need it (#146). Each use case requires only the operations it uses.
// nextFrame() resolves once the page has had a chance to paint; wait(ms) resolves after that many milliseconds.

export const FRAMES = Object.freeze({name: 'Clock', operations: Object.freeze(['nextFrame'])});
export const DELAYS = Object.freeze({name: 'Clock', operations: Object.freeze(['wait'])});
export const CLOCK = Object.freeze({name: 'Clock', operations: Object.freeze([...FRAMES.operations, ...DELAYS.operations])});
