import unittest

from music_analyzer.application.dto.models import ModelError, ModelResult
from music_analyzer.application.use_cases.models import DownloadModels, VerifyModels


class Storage:
    def __init__(self):
        self.calls = []

    def verify(self, model):
        self.calls.append(('verify', model))
        return ModelResult(model, True, 'local-sha256', 'Integrity only; inference not tested.')

    def install(self, model):
        self.calls.append(('install', model))
        if model == 'broken':
            raise ModelError('Transfer interrupted; retry.')
        return self.verify(model)


class ModelUseCaseTests(unittest.TestCase):
    def test_download_continues_after_failure_and_reports_non_readiness(self):
        storage = Storage()
        report = DownloadModels(storage, ('broken', 'good')).execute()
        self.assertFalse(report.ready)
        self.assertFalse(report.inference_validated)
        self.assertEqual([r.model_id for r in report.models], ['broken', 'good'])
        self.assertIn('retry', report.models[0].detail)
        self.assertTrue(report.models[1].available)

    def test_verify_does_not_download(self):
        storage = Storage()
        report = VerifyModels(storage, ('one', 'two')).execute()
        self.assertTrue(report.ready)
        self.assertFalse(report.inference_validated)
        self.assertEqual(storage.calls, [('verify', 'one'), ('verify', 'two')])

    def test_empty_selection_is_not_ready(self):
        self.assertFalse(VerifyModels(Storage(), ()).execute().ready)
