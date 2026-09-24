"""Application orchestration for Phase2 explorer candidate selection."""
from music_exporer.application.dto.candidates import CandidateQuery, CandidateResultDto, CandidateSummaryDto
from music_exporer.application.dto.explorer import AutomaticEvidence, ExplorerFieldEvidence, ExplorerMetadata
from music_exporer.application.ports.explorer import ExplorerRepository
from music_exporer.domain.candidate_selection import CandidateFeatures, FeatureEvidence, SelectionControl, SelectionRequest, rank_candidates

FEATURE_CONTRACT_VERSION = 'summary-derived-v1'
OVERRIDE_POLICY_VERSION = 'manual-text-display-only-v1'


class SelectExplorerCandidates:
    def __init__(self, repository: ExplorerRepository):
        self.repository = repository

    def execute(self, query: CandidateQuery):
        if query.after is not None:
            raise ValueError('Cursor paging is not supported for candidate selection')
        if not isinstance(query.limit, int) or query.limit < 1 or query.limit > 500:
            raise ValueError('Candidate limit must be between 1 and 500')
        raw_meta, records = self.repository.candidate_snapshot()
        records = tuple(records)
        total = len(records)
        by_id = {record.track_id: record for record in records}
        if query.current_track_id not in by_id:
            raise ValueError('Unknown current track')
        metadata = ExplorerMetadata(
            application_id=int(raw_meta.get('application_id', 0)),
            schema_version=int(raw_meta.get('schema_version', 0)),
            read_policy=str(raw_meta.get('read_policy', 'coherent_in_memory_snapshot')),
            track_count=total,
            feature_contract_version=FEATURE_CONTRACT_VERSION,
        )
        current = _features(by_id[query.current_track_id])
        candidates = tuple(_features(record) for record in records if record.track_id != query.current_track_id)
        controls = tuple(SelectionControl(c.name, c.mode, c.weight, c.parameters, c.within) for c in query.controls)
        domain_result = rank_candidates(current, candidates, SelectionRequest(controls, query.limit, query.exclude_track_ids))
        labels = {record.track_id: record.display_label for record in records}
        suggestions = domain_result.no_match_suggestions
        if len(records) == 1:
            suggestions = suggestions + ('No candidates are available in a one-track catalogue',)
        versions = dict(domain_result.policy_versions)
        versions['feature_contract_version'] = FEATURE_CONTRACT_VERSION
        versions['override_policy_version'] = OVERRIDE_POLICY_VERSION
        return CandidateResultDto(
            metadata=metadata,
            policy_versions=versions,
            current_track_id=query.current_track_id,
            controls_echo=query.controls,
            candidates=tuple(CandidateSummaryDto(r.track_id, labels.get(r.track_id, ''), i + 1, r.tier, r.score, r.supported_weight_mass, r.missing_weight_mass, r.requested_weight_mass, r.explanation) for i, r in enumerate(domain_result.candidates)),
            excluded_summary=domain_result.excluded_summary,
            no_match_suggestions=suggestions,
            no_match_details=domain_result.no_match_details,
        )


def _features(record):
    mapped = {}
    stages = {stage.stage: stage for stage in record.run.stages} if record.run else {}
    manual = dict(record.overrides)
    for field in ('bpm', 'key', 'genres', 'mood', 'energy'):
        stage = stages.get(field)
        automatic_values = stage.values if stage else ()
        summary_values = tuple(zip(stage.summary.labels, stage.summary.mean)) if stage and stage.summary else ()
        manual_text = manual.get(field)
        source = 'manual_text' if manual_text is not None else ('automatic' if automatic_values or summary_values else 'missing')
        app_evidence = ExplorerFieldEvidence(field=field, automatic=_automatic(stage, summary_values), manual_text=manual_text, effective_source=source, typed_override_status='unresolved' if manual_text is not None else 'absent')
        mapped[field] = FeatureEvidence(app_evidence.automatic_values, app_evidence.summary_values, app_evidence.manual_text, app_evidence.effective_source, app_evidence.provenance, app_evidence.uncertainty)
    return CandidateFeatures(record.track_id, mapped)


def _automatic(stage, summary_values):
    if stage is None:
        return AutomaticEvidence()
    return AutomaticEvidence(stage.values, summary_values, stage.summary.coverage if stage.summary else None, stage.provenance, stage.uncertainty)
