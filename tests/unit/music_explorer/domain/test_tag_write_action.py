"""Issue #132: the lifecycle of one tag-write action, previewed then approved once, then applied or rejected."""
import unittest

from music_explorer.domain.tag_write_action import (
    TAG_WRITE_ACTION_STATES, TagWriteActionTransitionError, next_tag_write_action_state)


class TagWriteActionLifecycleTests(unittest.TestCase):
    def test_a_previewed_action_is_approved_then_applied(self):
        state = next_tag_write_action_state('previewed', 'approve')
        self.assertEqual('approved', state)
        self.assertEqual('applied', next_tag_write_action_state(state, 'apply'))

    def test_a_previewed_or_approved_action_can_be_rejected(self):
        for state in ('previewed', 'approved'):
            with self.subTest(state=state):
                self.assertEqual('rejected', next_tag_write_action_state(state, 'reject'))

    def test_every_illegal_transition_is_refused(self):
        legal = {('previewed', 'approve'), ('previewed', 'reject'), ('approved', 'apply'), ('approved', 'reject')}
        for state in TAG_WRITE_ACTION_STATES:
            for action in ('approve', 'apply', 'reject', 'preview'):
                if (state, action) in legal:
                    continue
                with self.subTest(state=state, action=action):
                    with self.assertRaisesRegex(TagWriteActionTransitionError, f'cannot {action} while {state}'):
                        next_tag_write_action_state(state, action)

    def test_an_approval_is_spent_once_the_action_ends(self):
        for ended in ('applied', 'rejected'):
            with self.subTest(ended=ended):
                with self.assertRaises(TagWriteActionTransitionError):
                    next_tag_write_action_state(ended, 'approve')

    def test_an_unknown_state_is_refused(self):
        with self.assertRaises(TagWriteActionTransitionError):
            next_tag_write_action_state('written', 'apply')


if __name__ == '__main__':
    unittest.main()
