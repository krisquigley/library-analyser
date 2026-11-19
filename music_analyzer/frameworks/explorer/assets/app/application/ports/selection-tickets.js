// The tab's selection tickets (#146). The server applies a selection only if its ticket is newer
// than the last one this tab sent, so a slow request cannot undo a later choice.
// nextTicket() returns the next ticket number; clientId() names this tab, the same on every call.

export const SELECTION_TICKETS = Object.freeze({name: 'SelectionTickets', operations: Object.freeze(['nextTicket', 'clientId'])});
