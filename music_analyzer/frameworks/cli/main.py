"""Composition root: the only place that assembles concrete dependencies."""
from music_analyzer.interface_adapters.mappers.review import review_to_mapping
import argparse
import os
import json
import sys
import hashlib
from pathlib import Path
import subprocess

from music_analyzer.application.use_cases.analyze_batch import AnalyzeBatch
from music_analyzer.infrastructure.persistence.batch import SQLiteBatchQueue
from music_analyzer.infrastructure.analysis.embedding_cache import FileEmbeddingCache
from music_analyzer.infrastructure.analysis.fingerprint import recipe_fingerprint
from music_analyzer.interface_adapters.presenters.batch import present_batch

from music_analyzer.application.use_cases.scan_library import ScanLibrary, ResolveTrack
from music_analyzer.application.dto.catalogue import ScanLimits
from music_analyzer.infrastructure.filesystem.inventory import LocalInventory
from music_analyzer.interface_adapters.presenters.catalogue import present_scan
from music_analyzer.application.use_cases.analyze_track import AnalyzeTrack
from music_analyzer.application.dto.analysis import AudioSource
from music_analyzer.domain.analysis import finite
from music_analyzer.infrastructure.analysis.essentia import EssentiaEngine, VerifiedModels, load_backend
from music_analyzer.infrastructure.audio.ffmpeg import FFmpegDecoder
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository
from music_analyzer.interface_adapters.presenters.analysis import present_analysis
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
from music_analyzer.application.use_cases.projection_artifacts import PrepareProjectionArtifact, RefreshProjectionArtifact
from music_analyzer.infrastructure.filesystem.projection_artifacts import FileProjectionArtifactStore
from music_analyzer.infrastructure.persistence.explorer_readonly import ReadOnlyExplorerSQLiteRepository


from music_analyzer.application.use_cases.review import ReviewTracks
from music_analyzer.infrastructure.filesystem.review_output import FileReviewOutput
from music_analyzer.interface_adapters.presenters.markdown import markdown_track, MARKDOWN_HEADER
from music_analyzer.interface_adapters.presenters.review import present_review


def build_doctor(**overrides) -> RunDoctor:
    settings = load_settings(**overrides)
    storage, model_ids = build_models(settings)
    return RunDoctor([PythonProbe(), PlatformProbe(), FFmpegProbe(), EssentiaProbe(),
                      CheckModels(VerifyModels(storage, model_ids))], settings=settings)


def build_models(settings):
    manifest = load_manifest()
    return FileModelStorage(settings.model_directory, manifest, HTTPSTransfer()), tuple(manifest)


def build_embedding_cache():
    root = os.environ.get('XDG_CACHE_HOME', '')
    base = Path(root) if root and Path(root).is_absolute() else Path.home() / '.cache'
    return FileEmbeddingCache(base / 'music-analyzer/embeddings-v1')


def build_analysis(**overrides):
    settings = load_settings(**overrides)
    library, version, reader = load_backend()
    storage, _ = build_models(settings)
    engine = EssentiaEngine(library, version, storage.manifest, VerifiedModels(storage), reader, cache=build_embedding_cache())
    return AnalyzeTrack(FFmpegDecoder(), engine, SQLiteAnalysisRepository(settings.database))


def build_batch_worker(settings, max_duration):
    # Read-only verification. No implicit download, including on an empty queue.
    library, version, reader = load_backend()
    storage, model_ids = build_models(settings)
    models = VerifiedModels(storage)
    hashes = {model: models(model)[1] for model in model_ids}
    decoder_version = subprocess.run(['ffmpeg', '-version'], check=True, capture_output=True,
                                     text=True, timeout=10).stdout
    package = Path(__file__).resolve().parents[2]
    algorithm = {name: hashlib.sha256((package / name).read_bytes()).hexdigest() for name in (
        'infrastructure/analysis/essentia.py', 'domain/analysis.py',
        'application/use_cases/analyze_track.py', 'infrastructure/audio/ffmpeg.py')}
    recipe = recipe_fingerprint(models=hashes, manifest=storage.manifest,
        engine=f'{version};numpy={reader.numpy.__version__}', decoder=decoder_version,
        preprocessing='ffmpeg-mono-44100-f32le;sections-v1', algorithm=algorithm,
        max_duration=max_duration)
    engine = EssentiaEngine(library, version, storage.manifest, models, reader, cache=build_embedding_cache())
    worker = AnalyzeTrack(FFmpegDecoder(), engine, SQLiteBatchQueue(settings.database))
    return recipe, worker.execute


def build_batch(settings, max_duration):
    queue = SQLiteBatchQueue(settings.database)
    files = LocalInventory()
    resolver = ResolveTrack(queue, files)
    selected = {}
    worker = []
    def recipe():
        fingerprint, analyze = build_batch_worker(settings, max_duration)
        worker.append(analyze)
        return fingerprint
    def resolve(track):
        source = resolver.execute(track)
        selected[track] = source.location
        return source
    def verify(track):
        if track in selected:
            return files.matches(selected[track], track)
        return any(files.matches(path, track) for path in queue.locations(track))
    return AnalyzeBatch(queue, resolve, lambda source, duration: worker[0](source, duration), verify), recipe


def add_configuration_options(parser: argparse.ArgumentParser) -> None:
    for option, help_text in (
        ("--config", "Read this TOML file instead of the optional XDG config file."),
        ("--database", "Override the dedicated analysis database path."),
        ("--model-directory", "Override the model bundle directory."),
    ):
        parser.add_argument(option, default=argparse.SUPPRESS, help=help_text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='music-analyzer', description='Local catalogue and single-worker analysis.')
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
    scan = commands.add_parser('scan', help='Inventory an explicitly selected root without changing audio tags.')
    add_configuration_options(scan)
    scan.add_argument('root')
    scan.add_argument('--max-entries', type=int, default=10000)
    scan.add_argument('--max-file-bytes', type=int, default=512 * 1024 * 1024)
    scan.add_argument('--max-total-bytes', type=int, default=8 * 1024 * 1024 * 1024)
    scan.add_argument('--json', action='store_true')
    status = commands.add_parser('status', help='Show durable batch job states (no inference).')
    add_configuration_options(status)
    status.add_argument('--json', action='store_true')
    analyze = commands.add_parser('analyze', help='Dispatch catalogue jobs, or analyze an explicit file/track.')
    add_configuration_options(analyze)
    source = analyze.add_mutually_exclusive_group()
    source.add_argument('--file', help='Explicit local audio path.')
    source.add_argument('--track', help='Exact-file track ID returned by scan.')
    analyze.add_argument('--limit', type=int, help='Maximum attempted tracks this invocation.')
    analyze.add_argument('--retry-failed', action='store_true', help='Retry failures, at most three attempts per recipe.')
    analyze.add_argument('--force', action='store_true', help='Reset attempt budget and rerun selected tracks.')
    analyze.add_argument('--max-duration', type=float, default=900, help='Reject longer audio; default 900s, maximum 3600s.')
    analyze.add_argument('--json', action='store_true', help='Print complete raw scores and provenance as JSON.')
    for name in ('show', 'reaggregate'):
        command = commands.add_parser(name, help='Inspect stored evidence; no decoding or inference.')
        add_configuration_options(command)
        command.add_argument('track_id', metavar='TRACK_ID')
        command.add_argument('--json', action='store_true')
        if name == 'reaggregate': command.add_argument('--threshold', type=float, required=True)
    listing = commands.add_parser('list', help='List catalogue identities with conservative review flags.')
    add_configuration_options(listing)
    listing.add_argument('--needs-review', action='store_true')
    override = commands.add_parser('override', help='Set or clear a manual text annotation by track and field.')
    add_configuration_options(override)
    operations = override.add_subparsers(dest='operation', required=True)
    for name in ('set', 'clear'):
        command = operations.add_parser(name)
        add_configuration_options(command)
        command.add_argument('track_id', metavar='TRACK_ID')
        command.add_argument('field', choices=('bpm', 'key', 'genres', 'mood', 'instruments', 'energy'))
        if name == 'set': command.add_argument('value')
    export = commands.add_parser('export', help='Export all catalogue review records; new output path required.')
    add_configuration_options(export)
    export.add_argument('--format', choices=('json', 'csv', 'markdown'), required=True)
    export.add_argument('--output', required=True)
    projection = commands.add_parser('prepare-projection', help='Prepare or refresh the read-only explorer projection artifact.')
    add_configuration_options(projection)
    projection.add_argument('--artifact', required=True, help='Projection artifact JSON path, separate from the analysis database.')
    projection.add_argument('--refresh', action='store_true', help='Refresh with the persisted transform instead of initial preparation.')
    projection.add_argument('--relayout', action='store_true', help='Explicitly refit anchors and ranges during refresh.')
    projection.add_argument('--k', type=int, default=10, help='Maximum undirected neighbour degree; default 10.')
    projection.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    if args.command == 'analyze' and (not finite(args.max_duration) or not 0 < args.max_duration <= 3600):
        parser.error('--max-duration must be positive, finite and at most 3600 seconds')
    if args.command == 'analyze':
        if args.limit is not None and args.limit <= 0:
            parser.error('--limit must be positive')
        if (args.file or args.track) and (args.limit is not None or args.retry_failed or args.force):
            parser.error('Batch options cannot be used with --file or --track')
    try:
        overrides = {key: value for key, value in vars(args).items()
                     if key in {'config', 'database', 'model_directory'}}
        if args.command in {'show', 'list', 'override', 'export', 'reaggregate'}:
            review = ReviewTracks(SQLiteAnalysisRepository(load_settings(**overrides).database))
            if args.command == 'list':
                print('TRACK_ID\tNEEDS_REVIEW\tRUN_STATUS')
                for report in review.list(args.needs_review):
                    print(f'{report.track.track_id}\t{report.needs_review}\t{report.track.run.status if report.track.run else "missing"}')
                return 0
            if args.command == 'export':
                review.export(FileReviewOutput(review_to_mapping, markdown_track, MARKDOWN_HEADER), args.format, args.output)
                output = 'Exported ' + args.output
            elif args.command == 'override':
                output = present_review(review.override(args.track_id, args.field,
                    args.value if args.operation == 'set' else None))
            else:
                output = present_review(review.show(args.track_id, getattr(args, 'threshold', None)), args.json)
            ready = True
        elif args.command == 'doctor':
            report = build_doctor(**overrides).execute()
            output = present_doctor(report, as_json=args.json)
            ready = report.foundation_ready
        elif args.command == 'scan':
            limits = ScanLimits(args.max_entries, args.max_file_bytes, args.max_total_bytes)
            settings = load_settings(**overrides)
            report = ScanLibrary(LocalInventory(), SQLiteAnalysisRepository(settings.database)).execute(args.root, limits)
            output = present_scan(report, as_json=args.json)
            ready = report.complete
        elif args.command == 'status':
            jobs = SQLiteBatchQueue(load_settings(**overrides).database).status()
            output, ready = present_batch(jobs, args.json), True
        elif args.command == 'analyze' and not (args.file or args.track):
            batch, recipe = build_batch(load_settings(**overrides), args.max_duration)
            jobs = batch.execute(recipe, args.limit, args.retry_failed, args.force, args.max_duration)
            output, ready = present_batch(jobs, args.json), not any(j.state == 'failed' for j in jobs)
        elif args.command == 'analyze':
            source = AudioSource(args.file) if args.file else ResolveTrack(
                SQLiteAnalysisRepository(load_settings(**overrides).database), LocalInventory()).execute(args.track)
            report = build_analysis(**overrides).execute(source, args.max_duration)
            output = present_analysis(report, as_json=args.json)
            ready = report.status == 'completed'
        elif args.command == 'prepare-projection':
            settings = load_settings(**overrides)
            repository = ReadOnlyExplorerSQLiteRepository(settings.database)
            store = FileProjectionArtifactStore(args.artifact, source_database_path=settings.database)
            if args.refresh:
                result = RefreshProjectionArtifact(repository, store, args.k).execute(explicit_relayout=args.relayout)
            else:
                if args.relayout:
                    parser.error('--relayout requires --refresh')
                result = PrepareProjectionArtifact(repository, store, args.k).execute()
            summary = {'artifact': args.artifact, 'fingerprint': result.artifact['fingerprint'], 'tracks': len(result.artifact['tracks']), 'edges': len(result.artifact['edges'])}
            output = json.dumps(summary, sort_keys=True) if args.json else f"Prepared {summary['tracks']} tracks, {summary['edges']} edges at {args.artifact}"
            ready = True
        else:
            storage, model_ids = build_models(load_settings(**overrides))
            use_case = DownloadModels if args.action == 'download' else VerifyModels
            report = use_case(storage, model_ids).execute()
            output = present_models(report, as_json=args.json)
            ready = report.ready
    except ConfigurationError as error:
        parser.error(str(error))
    except KeyboardInterrupt:
        print('music-analyzer: interrupted; completed analysis stages retained; temporary work cleaned up. Batch analyze resumes pending work; explicit --file/--track starts a new run.', file=sys.stderr)
        return 130
    except Exception as error:
        if args.command == 'scan' and args.json:
            print(json.dumps({'root': args.root, 'complete': False, 'files': [], 'missing': [],
                              'issues': [{'location': args.root, 'detail': str(error)}]}))
            return 1
        if args.command in {'analyze', 'status'} and args.json:
            print(json.dumps({'run_id': None, 'status': 'setup_failed', 'stages': [], 'detail': str(error)}))
            return 1
        print(f'music-analyzer: {args.command} failed: {error}', file=sys.stderr)
        return 1
    print(output)
    return 0 if ready else 1
