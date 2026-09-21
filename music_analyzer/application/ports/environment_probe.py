from typing import Protocol

from music_analyzer.application.dto.doctor import CheckResult


class EnvironmentProbe(Protocol):
    def check(self) -> CheckResult: ...
