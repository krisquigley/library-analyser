"""Run a Node test script and prove it reached its end (#125).

A Node process exits 0 when its event loop drains, even if an async block is
still awaiting a promise that will never settle. Such a script skips every
assertion after that await and still "passes". Async scripts must therefore
print NODE_SCRIPT_COMPLETED as their last step, and this runner requires it.
"""
import subprocess
from pathlib import Path

NODE_SCRIPT_COMPLETED = 'NODE_SCRIPT_COMPLETED'
REPO_ROOT = Path(__file__).resolve().parents[2]
_ASYNC_MARKERS = ('async ', '.then(', 'await ')


def run_node_script(test, script, *args, timeout=60):
    is_async = any(marker in script for marker in _ASYNC_MARKERS)
    if is_async and NODE_SCRIPT_COMPLETED not in script:
        test.fail(f'An async Node script must print {NODE_SCRIPT_COMPLETED} as its last step')
    result = subprocess.run(['node', '-e', script, *map(str, args)], cwd=REPO_ROOT,
                            capture_output=True, text=True, timeout=timeout)
    test.assertEqual(0, result.returncode, result.stdout + result.stderr)
    if is_async:
        test.assertIn(NODE_SCRIPT_COMPLETED, result.stdout,
                      'The script exited before its last assertion (an await never settled): ' + result.stderr)
    return result
