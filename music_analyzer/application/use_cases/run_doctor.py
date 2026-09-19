from collections.abc import Sequence

from music_analyzer.application.dto.doctor import DoctorReport
from music_analyzer.application.ports.environment_probe import EnvironmentProbe


class RunDoctor:
    """Assess configured foundation checks; availability is not inference validation."""

    def __init__(self, probes: Sequence[EnvironmentProbe]) -> None:
        if not probes:
            raise ValueError('At least one environment probe is required.')
        self._probes = tuple(probes)

    def execute(self) -> DoctorReport:
        checks = tuple(probe.check() for probe in self._probes)
        return DoctorReport(
            checks=checks,
            foundation_ready=all(check.available for check in checks),
            analysis_ready=False,
            remaining_validation=(
                'Model manifests, downloads, integrity and license records are not implemented.',
                'Validate FLAC, MP3 and M4A decoding and every selected model on target hardware.',
                'Confirm RAM and a compatible Python/Essentia TensorFlow build; pin the tested combination.',
                'Configuration and XDG path validation are not implemented.',
            ),
        )
