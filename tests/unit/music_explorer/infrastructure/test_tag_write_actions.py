"""Issue #132: previewed tag-write actions are kept in memory behind unguessable single-use tokens."""
import unittest

from music_explorer.application.ports.tag_write_actions import TagWriteAction
from music_explorer.infrastructure.tag_write_actions import InMemoryTagWriteActions


def action(token, state='previewed'):
    return TagWriteAction(token, state, ('t1',), 'fill-empty', 0.5, (), ())


class InMemoryTagWriteActionsTests(unittest.TestCase):
    def test_tokens_are_long_random_and_distinct(self):
        actions = InMemoryTagWriteActions()
        tokens = {actions.new_token() for _ in range(50)}
        self.assertEqual(50, len(tokens))
        self.assertTrue(all(len(token) >= 32 for token in tokens))

    def test_an_action_is_found_by_its_token_and_saving_again_replaces_its_state(self):
        actions = InMemoryTagWriteActions()
        actions.save(action('a'))
        actions.save(action('a', 'applied'))
        self.assertEqual('applied', actions.find('a').state)
        self.assertIsNone(actions.find('b'))

    def test_only_the_most_recent_actions_are_kept(self):
        actions = InMemoryTagWriteActions(capacity=2)
        for token in ('a', 'b', 'c'):
            actions.save(action(token))
        self.assertEqual((None, 'b', 'c'), tuple(getattr(actions.find(t), 'token', None) for t in ('a', 'b', 'c')))


if __name__ == '__main__':
    unittest.main()
