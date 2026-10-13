"""Fresh D1 dispatch RED; this parser seam deliberately does not prove syntax.

Only existing imports are used. A parsed explicit integrity request must not
fall through to the model command or initialize configured/writable services.
Real parser, module entrypoint, and full LIMITED report tests are later packets.
"""
import argparse
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from music_analyzer.frameworks.cli.main import main
from tests.integration.infrastructure.integrity_d1_public_fixture import create_public_core_database


class IntegrityDispatchBoundaryTests(unittest.TestCase):
    def test_explicit_integrity_request_never_dispatches_models_or_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'healthy.sqlite'
            track_ids = create_public_core_database(path, version=10)
            self.assertEqual(len(track_ids), 2)
            before = {file.name: file.read_bytes() for file in Path(directory).iterdir()}
            argv = ['integrity', '--database', str(path), '--json']
            request = argparse.Namespace(
                command='integrity', database=str(path), json=True,
                audit_deadline_seconds=120.0,
            )
            stdout, stderr = io.StringIO(), io.StringIO()
            with ExitStack() as stack:
                parse = stack.enter_context(patch(
                    'argparse.ArgumentParser.parse_args', return_value=request))
                # Let the fallback reach its forbidden service, without loading
                # user/default configuration. This spy must also remain unused.
                settings = stack.enter_context(patch(
                    'music_analyzer.frameworks.cli.main.load_settings',
                    return_value=argparse.Namespace(database=str(path))))
                guards = {}
                for name in (
                    'build_models', 'SQLiteAnalysisRepository', 'SQLiteBatchQueue',
                    'build_analysis', 'build_batch_worker', 'load_backend',
                    'FFmpegDecoder', 'create_server', 'ensure_current_graph_snapshot',
                ):
                    guards[name] = stack.enter_context(patch(
                        'music_analyzer.frameworks.cli.main.' + name,
                        side_effect=RuntimeError('forbidden integrity service: ' + name)))
                stack.enter_context(redirect_stdout(stdout))
                stack.enter_context(redirect_stderr(stderr))
                result = main(argv)

            parse.assert_called_once_with(argv)
            after = {file.name: file.read_bytes() for file in Path(directory).iterdir()}
            self.assertEqual(after, before, 'integrity must not mutate the fixture or sidecars')
            guards['SQLiteAnalysisRepository'].assert_not_called()
            guards['SQLiteBatchQueue'].assert_not_called()
            # Qualifying RED on main: the real dispatch fallback invokes this
            # existing model service. Parser/import/fixture errors are not RED.
            guards['build_models'].assert_not_called()
            settings.assert_not_called()
            for guard in guards.values():
                guard.assert_not_called()
            self.assertEqual(result, 4, 'D1 LIMITED is incomplete, never clean0')


if __name__ == '__main__':
    unittest.main()
