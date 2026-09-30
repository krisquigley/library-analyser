from dataclasses import replace

from music_analyzer.application.dto.analysis import AudioSource
from music_analyzer.application.dto.catalogue import Inventory, ScanLimits, ScanReport
from music_analyzer.application.ports.catalogue import Catalogue, FileInventory
from music_analyzer.domain.library_duration_policy import DurationVerification, active_library_duration_policy


class ScanLibrary:
    def __init__(self, files: FileInventory, catalogue: Catalogue):
        self.files, self.catalogue = files, catalogue

    def execute(self, root: str, limits: ScanLimits = ScanLimits()) -> ScanReport:
        inventory = self.files.inventory(root, limits)
        reported_files = []
        registered_files = []
        for file in inventory.files:
            decision = active_library_duration_policy(_duration_verification(file.metadata))
            reported = file if decision.active else _with_metadata_warning(file, decision.warning or '')
            reported_files.append(reported)
            registered_files.append(reported)
        registered_inventory = Inventory(inventory.root, tuple(registered_files), inventory.issues, inventory.complete)
        missing = self.catalogue.register(registered_inventory)
        return ScanReport(inventory.root, tuple(reported_files), inventory.issues, inventory.complete, missing)


def _duration_verification(metadata) -> DurationVerification | None:
    seconds = getattr(metadata, 'measured_duration_seconds', None)
    if seconds is None:
        seconds = getattr(metadata, 'duration_seconds', None)
    source = getattr(metadata, 'duration_source', '') or getattr(metadata, 'duration_verified_by', '')
    return DurationVerification(seconds, source) if source else None


def _with_metadata_warning(file, warning: str):
    metadata = file.metadata
    warnings = tuple(getattr(metadata, 'warnings', ()))
    metadata = replace(metadata, warnings=tuple(dict.fromkeys((*warnings, warning))))
    return replace(file, metadata=metadata)


class ResolveTrack:
    def __init__(self, catalogue: Catalogue, files: FileInventory):
        self.catalogue, self.files = catalogue, files

    def execute(self, track_id: str) -> AudioSource:
        for location in self.catalogue.locations(track_id):
            if self.files.matches(location, track_id):
                return AudioSource(location, track_id)
        raise ValueError('No verified available location for track; scan the selected root again or use --file PATH')
