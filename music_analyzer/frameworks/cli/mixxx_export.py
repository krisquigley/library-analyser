"""`music-analyzer export-mixxx` (#133): export the analysis to a NEW Mixxx 2.5 library file.

The arguments are checked here, at the boundary; the use case decides which tracks go and refuses an
existing destination, so a Mixxx database is never opened.
"""
import argparse

from music_analyzer.application.use_cases.export_mixxx_library.export_mixxx_library import (
    ExportMixxxLibrary, ExportMixxxLibraryRequest, MixxxLibraryExported, MixxxLibraryExportPlanned)
from music_analyzer.infrastructure.event_bus import InProcessEventBus
from music_analyzer.infrastructure.mixxx.library_file import SqliteMixxxLibraryFile
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository
from music_analyzer.interface_adapters.presenters.mixxx_export import (
    present_mixxx_export_planned, present_mixxx_exported, present_skipped_tracks)

COMMAND = 'export-mixxx'


def add_mixxx_export_command(commands, add_configuration_options):
    export = commands.add_parser(COMMAND, help='Export the active analysed tracks to a NEW Mixxx 2.5 library file.')
    add_configuration_options(export)
    export.add_argument('--output', required=True, type=_nonblank,
                        help='The new library file to create; an existing path is refused.')
    export.add_argument('--track', action='append', default=[], type=_nonblank, metavar='TRACK_ID',
                        help='Export only this track; repeat for more. Default: every active analysed track.')
    export.add_argument('--dry-run', action='store_true', help='Report what would be exported and write nothing.')


def run_mixxx_export_command(args, database: str) -> int:
    events = InProcessEventBus()
    events.subscribe(MixxxLibraryExportPlanned, lambda event: print(present_mixxx_export_planned(event)))
    events.subscribe(MixxxLibraryExported, lambda event: print(present_mixxx_exported(event)))
    use_case = ExportMixxxLibrary(SQLiteAnalysisRepository(database), SqliteMixxxLibraryFile(), events)
    request = ExportMixxxLibraryRequest(args.output, tuple(args.track))
    plan = use_case.preview(request) if args.dry_run else use_case.export(request)
    if plan.skipped:
        print(present_skipped_tracks(plan.skipped))
    return 0


def _nonblank(value):
    if not value.strip():
        raise argparse.ArgumentTypeError('must not be blank')
    return value
