// Selection tickets kept in the tab's sessionStorage (#146), so a reload carries on counting.
// Storage may be missing or refuse access (a private window, blocked site data): tickets then last for the page.

const TICKET_KEY = 'music-explorer-selection-post-seq';
const CLIENT_ID_KEY = 'music-explorer-selection-client-id';

export function sessionSelectionTickets({storage, now, random}) {
  let lastTicket = storedTicket(storage);
  let pageClientId = null;

  function nextTicket() {
    lastTicket += 1;
    store(storage, TICKET_KEY, String(lastTicket));
    return lastTicket;
  }

  function clientId() {
    try {
      if (storage) {
        let id = storage.getItem(CLIENT_ID_KEY);
        if (!id) {
          id = 'tab-' + now().toString(36) + '-' + randomPart(random);
          storage.setItem(CLIENT_ID_KEY, id);
        }
        return id;
      }
    } catch {
      // Fall through to an id for this page alone.
    }
    pageClientId = pageClientId || 'tab-' + randomPart(random);
    return pageClientId;
  }

  return Object.freeze({nextTicket, clientId});
}

function storedTicket(storage) {
  try {
    const value = Number(storage ? storage.getItem(TICKET_KEY) || '0' : 0);
    return Number.isFinite(value) && value > 0 ? Math.floor(value) : 0;
  } catch {
    return 0;
  }
}

function store(storage, key, value) {
  try {
    if (storage) storage.setItem(key, value);
  } catch {
    // The ticket still counts for this page.
  }
}

function randomPart(random) {
  return random().toString(36).slice(2);
}
