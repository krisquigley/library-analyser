import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from music_analyzer.frameworks.cli.main import main


class ModelCLITests(unittest.TestCase):
    def test_missing_models_json_and_doctor_honesty(self):
        with tempfile.TemporaryDirectory() as directory:
            for command in (['models', 'verify'], ['doctor']):
                output = io.StringIO()
                with redirect_stdout(output):
                    result = main(command + ['--model-directory', directory, '--json'])
                self.assertEqual(result, 1)
                report = json.loads(output.getvalue())
                if command[0] == 'models':
                    self.assertFalse(report['ready'])
                    self.assertFalse(report['inference_validated'])
                    self.assertEqual(len(report['models']), 6)
                else:
                    self.assertFalse(report['analysis_ready'])
                    self.assertTrue(any(c['name'] == 'models' and not c['available'] for c in report['checks']))

    def test_download_failure_is_json_and_nonzero(self):
        with tempfile.TemporaryDirectory() as directory, patch('music_analyzer.frameworks.cli.main.HTTPSTransfer') as transfer:
            from music_analyzer.application.dto.models import ModelError
            transfer.return_value.download.side_effect = ModelError('offline; retry')
            output = io.StringIO()
            with redirect_stdout(output):
                result = main(['--model-directory', directory, 'models', 'download', '--json'])
            self.assertEqual(result, 1)
            self.assertEqual(len(json.loads(output.getvalue())['models']), 6)

    def test_successful_fake_bundle_reports_integrity_not_inference(self):
        from music_analyzer.application.dto.models import ModelResult
        class Storage:
            def install(self, model_id):
                return self.verify(model_id)
            def verify(self, model_id):
                return ModelResult(model_id, True, 'local-sha256', 'Inference not tested.')
        with patch('music_analyzer.frameworks.cli.main.build_models', return_value=(Storage(), ('fake',))):
            for action in ('download', 'verify'):
                output = io.StringIO()
                with redirect_stdout(output):
                    result = main(['models', action, '--json'])
                self.assertEqual(result, 0)
                report = json.loads(output.getvalue())
                self.assertTrue(report['ready'])
                self.assertFalse(report['inference_validated'])

    def test_human_verify_and_config_between_subcommands(self):
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with redirect_stdout(output):
                result = main(['models', '--model-directory', directory, 'verify'])
            self.assertEqual(result, 1)
            self.assertIn('Inference validated: no', output.getvalue())
