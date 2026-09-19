from music_analyzer.application.dto.analysis import AudioSource
from music_analyzer.application.dto.catalogue import ScanLimits, ScanReport
from music_analyzer.application.ports.catalogue import Catalogue, FileInventory


class ScanLibrary:
    def __init__(self, files: FileInventory, catalogue: Catalogue):
        self.files, self.catalogue = files, catalogue

    def execute(self, root: str, limits: ScanLimits = ScanLimits()) -> ScanReport:
        inventory = self.files.inventory(root, limits)
        missing = self.catalogue.register(inventory)
        return ScanReport(inventory.root, inventory.files, inventory.issues, inventory.complete, missing)


class ResolveTrack:
    def __init__(self, catalogue: Catalogue, files: FileInventory):
        self.catalogue, self.files = catalogue, files

    def execute(self, track_id: str) -> AudioSource:
        for location in self.catalogue.locations(track_id):
            if self.files.matches(location, track_id):
                return AudioSource(location)
        raise ValueError('No verified available location for track; scan the selected root again or use --file PATH')
