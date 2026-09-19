"""Composition root: the only place that assembles concrete dependencies."""
import argparse
import sys

from music_analyzer.application.use_cases.run_doctor import RunDoctor
from music_analyzer.infrastructure.environment.probes import (
    EssentiaProbe, FFmpegProbe, PlatformProbe, PythonProbe,
)
from music_analyzer.interface_adapters.presenters.doctor import present_doctor


def build_doctor() -> RunDoctor:
    return RunDoctor([PythonProbe(), PlatformProbe(), FFmpegProbe(), EssentiaProbe()])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='music-analyzer', description='Partial Phase 1 environment discovery.')
    commands = parser.add_subparsers(dest='command', required=True)
    doctor = commands.add_parser('doctor', help='Check dependency availability (not analysis readiness).')
    doctor.add_argument('--json', action='store_true', help='Print a machine-readable report.')
    args = parser.parse_args(argv)
    try:
        report = build_doctor().execute()
        output = present_doctor(report, as_json=args.json)
    except Exception as error:
        print(f'music-analyzer: doctor failed: {error}', file=sys.stderr)
        return 1
    print(output)
    return 0 if report.foundation_ready else 1
