"""Composition root: the only place that assembles concrete dependencies."""
import argparse
import sys

from music_analyzer.application.use_cases.run_doctor import RunDoctor
from music_analyzer.application.use_cases.models import DownloadModels, VerifyModels
from music_analyzer.application.use_cases.check_models import CheckModels
from music_analyzer.infrastructure.models.manifest import load_manifest
from music_analyzer.infrastructure.models.storage import FileModelStorage
from music_analyzer.infrastructure.models.transfer import HTTPSTransfer
from music_analyzer.interface_adapters.presenters.models import present_models
from music_analyzer.infrastructure.config import ConfigurationError, load_settings
from music_analyzer.infrastructure.environment.probes import (
    EssentiaProbe, FFmpegProbe, PlatformProbe, PythonProbe,
)
from music_analyzer.interface_adapters.presenters.doctor import present_doctor


def build_doctor(**overrides) -> RunDoctor:
    settings = load_settings(**overrides)
    storage, model_ids = build_models(settings)
    return RunDoctor([PythonProbe(), PlatformProbe(), FFmpegProbe(), EssentiaProbe(),
                      CheckModels(VerifyModels(storage, model_ids))], settings=settings)


def build_models(settings):
    manifest = load_manifest()
    return FileModelStorage(settings.model_directory, manifest, HTTPSTransfer()), tuple(manifest)


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
    models = commands.add_parser('models', help='Download or verify the packaged model selection.')
    add_configuration_options(models)
    actions = models.add_subparsers(dest='action', required=True)
    for action in ('download', 'verify'):
        subcommand = actions.add_parser(action)
        add_configuration_options(subcommand)
        subcommand.add_argument('--json', action='store_true', help='Print a machine-readable report.')
    args = parser.parse_args(argv)
    try:
        overrides = {key: value for key, value in vars(args).items()
                     if key in {'config', 'database', 'model_directory'}}
        if args.command == 'doctor':
            report = build_doctor(**overrides).execute()
            output = present_doctor(report, as_json=args.json)
            ready = report.foundation_ready
        else:
            storage, model_ids = build_models(load_settings(**overrides))
            use_case = DownloadModels if args.action == 'download' else VerifyModels
            report = use_case(storage, model_ids).execute()
            output = present_models(report, as_json=args.json)
            ready = report.ready
    except ConfigurationError as error:
        parser.error(str(error))
    except KeyboardInterrupt:
        print('music-analyzer: interrupted; incomplete temporary download removed. Retry safely.', file=sys.stderr)
        return 130
    except Exception as error:
        print(f'music-analyzer: {args.command} failed: {error}', file=sys.stderr)
        return 1
    print(output)
    return 0 if ready else 1
