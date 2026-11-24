"""The lifecycle of one tag-write action (#132), as a transitions table.

The listener previews exactly which files and fields will change, then approves that one action. An
approval is spent when the action is applied or rejected (for example because a file changed since the
preview), so it never carries over to another action.
"""
_TRANSITIONS = {
    'previewed': {'approve': 'approved', 'reject': 'rejected'},
    'approved': {'apply': 'applied', 'reject': 'rejected'},
    'applied': {},
    'rejected': {},
}

TAG_WRITE_ACTION_STATES = tuple(_TRANSITIONS)


class TagWriteActionTransitionError(ValueError):
    pass


def next_tag_write_action_state(state: str, action: str) -> str:
    next_state = _TRANSITIONS.get(state, {}).get(action)
    if next_state is None:
        raise TagWriteActionTransitionError(f'A tag-write action cannot {action} while {state}')
    return next_state
