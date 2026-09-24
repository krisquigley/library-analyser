"""Map analyzer-produced read-only catalogue contracts into explorer-owned DTOs."""
from music_exporer.application.dto.explorer import AnalysisReport, ExplorerStoredTrack, ScoreSummary, StageResult


def map_analyzer_track(track) -> ExplorerStoredTrack:
    return ExplorerStoredTrack(
        track_id=track.track_id,
        sha256=track.sha256,
        size=track.size,
        display_label=track.display_label,
        available_locations=track.available_locations,
        run=map_analyzer_report(track.run) if track.run is not None else None,
        overrides=tuple(track.overrides),
    )


def map_analyzer_report(report) -> AnalysisReport:
    return AnalysisReport(report.run_id, report.status, tuple(map_analyzer_stage(stage) for stage in report.stages), report.detail)


def map_analyzer_stage(stage) -> StageResult:
    summary = None
    if stage.summary is not None:
        raw = stage.summary
        summary = ScoreSummary(raw.labels, raw.mean, raw.minimum, raw.maximum, raw.coverage, raw.provisional, raw.uncertainty)
    return StageResult(stage.stage, tuple(stage.provenance), stage.uncertainty, tuple(stage.values), (), summary)
