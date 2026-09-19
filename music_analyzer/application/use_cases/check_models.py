from music_analyzer.application.dto.doctor import CheckResult
from music_analyzer.application.use_cases.models import VerifyModels


class CheckModels:
    """Adapt model verification to the doctor's application probe boundary."""
    def __init__(self, verification: VerifyModels):
        self._verification = verification

    def check(self) -> CheckResult:
        report = self._verification.execute()
        failures = [model.model_id for model in report.models if not model.available]
        return CheckResult('models', report.ready,
                           'Model bundle integrity only; inference not tested.' if report.ready
                           else 'Missing or invalid model bundles: ' + ', '.join(failures),
                           'Run models verify for details; models download installs missing bundles.')
