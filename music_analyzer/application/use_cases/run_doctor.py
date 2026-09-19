from collections.abc import Sequence

from music_analyzer.application.dto.doctor import DoctorReport
from music_analyzer.application.dto.settings import Settings
from music_analyzer.application.ports.environment_probe import EnvironmentProbe


class RunDoctor:
    """Assess configured foundation checks; availability is not inference validation."""

    def __init__(self, probes: Sequence[EnvironmentProbe], *, settings: Settings | None = None) -> None:
        if not probes:
            raise ValueError('At least one environment probe is required.')
        self._probes = tuple(probes)
        self._settings = settings

    def execute(self) -> DoctorReport:
        checks = tuple(probe.check() for probe in self._probes)
        return DoctorReport(
            checks=checks,
            settings=self._settings,
            foundation_ready=all(check.available for check in checks),
            analysis_ready=False,
            remaining_validation=(
                'Configured paths do not validate database schemas, write permissions or model readiness.',
                'Model manifests, downloads, integrity and license records are not implemented.',
                'Validate FLAC, MP3 and M4A decoding and every selected model on target hardware.',
                'Confirm RAM and a compatible Python/Essentia TensorFlow build; pin the tested combination.',
            ),
        )
