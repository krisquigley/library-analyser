"""Composition root: the only place that assembles concrete dependencies."""
import argparse
import sys

from music_analyzer.application.use_cases.run_doctor import RunDoctor
from music_analyzer.infrastructure.config import ConfigurationError, load_settings
from music_analyzer.infrastructure.environment.probes import (
    EssentiaProbe, FFmpegProbe, PlatformProbe, PythonProbe,
)
from music_analyzer.interface_adapters.presenters.doctor import present_doctor


def build_doctor(**overrides) -> RunDoctor:
    settings = load_settings(**overrides)
    return RunDoctor([PythonProbe(), PlatformProbe(), FFmpegProbe(), EssentiaProbe()], settings=settings)


def add_configuration_options(parser: argparse.ArgumentParser) -> None:
    for option, help_text in (
        ("--config", "Read this TOML file instead of the optional XDG config file."),
        ("--database", "Override the analysis database path (no database is opened)."),
        ("--model-directory", "Override the model directory (no models are loaded)."),
    ):
        parser.add_argument(option, default=argparse.SUPPRESS, help=help_text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='music-analyzer', description='Partial Phase 1 environment discovery.')
    add_configuration_options(parser)
    commands = parser.add_subparsers(dest='command', required=True)
    doctor = commands.add_parser('doctor', help='Check dependency availability (not analysis readiness).')
    add_configuration_options(doctor)
    doctor.add_argument('--json', action='store_true', help='Print a machine-readable report.')
    args = parser.parse_args(argv)
    try:
        report = build_doctor(**{key: value for key, value in vars(args).items()
                                 if key in {'config', 'database', 'model_directory'}}).execute()
        output = present_doctor(report, as_json=args.json)
    except ConfigurationError as error:
        parser.error(str(error))
    except Exception as error:
        print(f'music-analyzer: doctor failed: {error}', file=sys.stderr)
        return 1
    print(output)
    return 0 if report.foundation_ready else 1
