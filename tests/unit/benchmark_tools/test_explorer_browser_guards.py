"""External resource admission is checked before starting browser processes."""
import unittest
from unittest.mock import patch
from tools.explorer_browser_diagnostic import require_memory_bound


class BrowserMemoryAdmission(unittest.TestCase):
    def reads(self, swap):
        values = {'memory.max': str(4 * 2**30), 'memory.oom.group': '1', 'memory.swap.max': swap}
        return lambda path: values[path.name]

    def test_swap_must_be_disabled(self):
        with patch('pathlib.Path.read_text', autospec=True, side_effect=self.reads('max')):
            with self.assertRaises(RuntimeError):
                require_memory_bound()

    def test_bounded_group_without_swap_is_admitted(self):
        with patch('pathlib.Path.read_text', autospec=True, side_effect=self.reads('0')):
            require_memory_bound()
