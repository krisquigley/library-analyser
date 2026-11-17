"""The Node test runner must fail a script that never reaches its end (#125)."""
import shutil
import unittest

from tests.support.node_script import run_node_script


class _Probe(unittest.TestCase):
    def runTest(self):
        pass


@unittest.skipUnless(shutil.which('node'), 'Node is required')
class NodeScriptRunnerTests(unittest.TestCase):
    def test_a_completed_async_script_passes(self):
        run_node_script(_Probe(), "(async () => { await Promise.resolve(); })()"
                                  ".then(() => console.log('NODE_SCRIPT_COMPLETED'))")

    def test_an_await_that_never_settles_fails_even_though_node_exits_0(self):
        hanging = ("(async () => { await new Promise(() => {}); throw new Error('never reached'); })()"
                   ".then(() => console.log('NODE_SCRIPT_COMPLETED'))")

        with self.assertRaisesRegex(AssertionError, 'exited before its last assertion'):
            run_node_script(_Probe(), hanging)

    def test_an_async_script_without_the_completion_marker_is_rejected(self):
        with self.assertRaisesRegex(AssertionError, 'must print NODE_SCRIPT_COMPLETED'):
            run_node_script(_Probe(), '(async () => {})()')

    def test_a_failing_script_fails(self):
        with self.assertRaises(AssertionError):
            run_node_script(_Probe(), "require('assert').fail('boom')")


if __name__ == '__main__':
    unittest.main()
