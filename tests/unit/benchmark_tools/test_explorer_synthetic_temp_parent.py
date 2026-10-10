"""Cleanup owns a canonical temp parent, not a caller's mutable alias.

All files are disposable synthetic data beneath a caller-owned canonical root.
Potential cleanup recursion runs only in a child with both an _exit alarm and a
parent kill timeout; parent cleanup never depends on the mutated symlink.
"""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


_REPRODUCTION = r'''
import os
from pathlib import Path
import signal
import sys
import tempfile
import traceback
from unittest.mock import patch

from tools import explorer_synthetic_fixture as module

signal.signal(signal.SIGALRM, lambda *_: os._exit(124))
signal.alarm(8)

class ExpectedFailure(Exception):
    pass

def check():
    scratch = Path(sys.argv[1]).resolve()
    mutation, lifecycle = sys.argv[2:]
    real = scratch / 'real'
    other = scratch / 'other'
    real.mkdir()
    other.mkdir()
    alias = scratch / 'alias'
    alias.symlink_to(real, target_is_directory=True)
    sentinel = None
    owned = None

    def mutate(path):
        nonlocal owned, sentinel
        owned = path.parent
        assert owned.parent == real, owned
        for suffix in ('-wal', '-shm', '-journal'):
            Path(str(path) + suffix).write_bytes(b'synthetic sidecar')
        # Same basename deliberately exists under the new alias target.
        # Cleanup must neither delete that root nor leave the real owned root.
        decoy = other / owned.name
        decoy.mkdir()
        sentinel = decoy / 'sentinel'
        sentinel.write_bytes(b'caller-owned synthetic sentinel')
        alias.unlink()
        if mutation == 'retarget':
            alias.symlink_to(other, target_is_directory=True)

    original_populate = module._populate
    def populate(path, *args):
        if lifecycle == 'construction_failure':
            path.write_bytes(b'synthetic unfinished catalogue')
            mutate(path)
            raise ExpectedFailure('construction')
        return original_populate(path, *args)

    try:
        with patch.object(tempfile, 'tempdir', str(alias)), patch.object(
                module, '_populate', side_effect=populate):
            with module.public_synthetic_fixture() as fixture:
                mutate(fixture['db_path'])
                if lifecycle == 'consumer_failure':
                    raise ExpectedFailure('consumer')
    except ExpectedFailure as error:
        assert lifecycle != 'success', error
        expected = 'construction' if lifecycle == 'construction_failure' else 'consumer'
        assert str(error) == expected, error
    else:
        assert lifecycle == 'success', lifecycle
    assert owned is not None
    assert not owned.exists(), 'canonical owned root leaked: ' + str(owned)
    assert list(real.iterdir()) == [], 'owned database or sidecars leaked'
    assert sentinel.read_bytes() == b'caller-owned synthetic sentinel'
    assert list(sentinel.parent.iterdir()) == [sentinel]
    assert list(other.iterdir()) == [sentinel.parent]

status = 0
try:
    check()
except BaseException:
    traceback.print_exc()
    status = 1
finally:
    # Avoid interpreter finalizers re-entering a buggy cleanup after failure.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(status)
'''


class ExplorerSyntheticTempParentTests(unittest.TestCase):
    def test_mutated_temp_parent_alias_cannot_redirect_or_prevent_cleanup(self):
        for mutation in ('unlink', 'retarget'):
            for lifecycle in ('success', 'consumer_failure', 'construction_failure'):
                with self.subTest(mutation=mutation, lifecycle=lifecycle):
                    # The outer root is never aliased and always cleaned, even
                    # when the child hangs, crashes or fails an assertion.
                    with tempfile.TemporaryDirectory(
                            prefix='synthetic-parent-regression-',
                            dir=Path(tempfile.gettempdir()).resolve()) as scratch:
                        try:
                            completed = subprocess.run(
                                [sys.executable, '-B', '-c', _REPRODUCTION,
                                 str(Path(scratch).resolve()), mutation, lifecycle],
                                capture_output=True, text=True, timeout=12,
                            )
                        except subprocess.TimeoutExpired as error:
                            self.fail(f'child cleanup exceeded hard timeout: {error}')
                        self.assertEqual(completed.returncode, 0,
                                         completed.stdout + completed.stderr)


if __name__ == '__main__':
    unittest.main()
