import unittest

from music_analyzer.application.dto.analysis import AnalysisReport, StageResult
from music_analyzer.domain.analysis import ScoreSummary
from music_analyzer.application.dto.explorer import ExplorerStoredTrack
from music_analyzer.application.use_cases.projection_artifacts import (
    LoadProjectionArtifact,
    PrepareProjectionArtifact,
    ProjectionArtifactError,
    RefreshProjectionArtifact,
    _fingerprint,
)


class FakeExplorerRepository:
    def __init__(self, records):
        self.records = tuple(records)

    def metadata(self):
        return {'application_id': 0x4D414E41, 'schema_version': 4, 'read_policy': 'bounded_read_transaction'}

    def candidate_snapshot(self):
        return self.metadata(), self.records


class SpyArtifactStore:
    def __init__(self, existing=None, fail_replace=False):
        self.existing = existing
        self.fail_replace = fail_replace
        self.replaced = []
        self.loaded = 0

    def load(self):
        self.loaded += 1
        if self.existing is None:
            raise ProjectionArtifactError('missing')
        return self.existing

    def replace(self, artifact):
        if self.fail_replace:
            raise ProjectionArtifactError('replace failed')
        self.existing = artifact
        self.replaced.append(artifact)


def track(track_id, *, bpm=120.0, arousal=0.0, detail='/private/music/raw.json'):
    run = AnalysisReport(
        run_id='run-' + track_id,
        status='completed',
        stages=(
            StageResult('bpm', (), '', (('bpm', bpm),)),
            StageResult('energy', (), '', (), summary=ScoreSummary(('arousal',), (arousal,), (arousal,), (arousal,), 1.0, False, '')),
        ),
        detail=detail,
    )
    return ExplorerStoredTrack(
        track_id=track_id,
        sha256=track_id[-64:] if len(track_id) >= 64 else track_id.rjust(64, '0'),
        size=123,
        display_label='Track ' + track_id,
        available_locations=1,
        run=run,
        overrides=(),
    )


class ProjectionArtifactUseCaseContractTests(unittest.TestCase):
    def test_prepare_uses_snapshot_and_replaces_valid_artifact_without_private_details(self):
        store = SpyArtifactStore()
        result = PrepareProjectionArtifact(FakeExplorerRepository((track('a'), track('b', bpm=130, arousal=1.0))), store).execute()

        self.assertEqual(len(store.replaced), 1)
        self.assertEqual(result.artifact['artifact_version'], 'journey-projection-artifact-v1')
        serialized = repr(result.artifact)
        self.assertNotIn('/private/music', serialized)
        self.assertNotIn('raw_predictions', serialized)
        self.assertIn('fingerprint', result.artifact)
        self.assertIn('transform', result.artifact)

    def test_fingerprint_invalidates_when_projection_contract_versions_change(self):
        records = (track('a'), track('b', bpm=130, arousal=1.0))
        metadata = FakeExplorerRepository(records).metadata()
        from music_analyzer.application.use_cases import projection_artifacts as module
        original = _fingerprint(metadata, records, module.ProjectionParameters(k=10))
        prior = module.ARTIFACT_VERSION
        try:
            module.ARTIFACT_VERSION = prior + '-next'
            changed = _fingerprint(metadata, records, module.ProjectionParameters(k=10))
        finally:
            module.ARTIFACT_VERSION = prior
        self.assertNotEqual(changed, original)

    def test_artifact_records_full_projection_contract_versions(self):
        result = PrepareProjectionArtifact(FakeExplorerRepository((track('a'), track('b', bpm=130, arousal=1.0))), SpyArtifactStore()).execute()

        versions = result.artifact['policy_versions']
        self.assertEqual(versions['projection_feature_contract_version'], 'projection-features-v1')
        self.assertEqual(versions['projection_fingerprint_version'], 'projection-fingerprint-v1')
        self.assertEqual(versions['projection_refresh_policy_version'], 'fixed-transform-refresh-v1')
        self.assertEqual(versions['neighbour_policy_version'], 'endpoint-local-exact-top-k-neighbours-v2')
        self.assertIn('distance_policy_version', versions)

    def test_prepare_preserves_prior_artifact_when_replacement_fails(self):
        prior = {'artifact_version': 'journey-projection-artifact-v1', 'sentinel': 'prior'}
        store = SpyArtifactStore(existing=prior, fail_replace=True)

        with self.assertRaises(ProjectionArtifactError):
            PrepareProjectionArtifact(FakeExplorerRepository((track('a'), track('b'),)), store).execute()
        self.assertIs(store.existing, prior)
        self.assertEqual(store.replaced, [])

    def test_load_is_readonly_and_never_repairs_or_rebuilds(self):
        store = SpyArtifactStore(existing={'artifact_version': 'journey-projection-artifact-v1', 'transform': {'policy_version': 'anchor-distance-projection-v1'}, 'tracks': (), 'edges': ()})
        result = LoadProjectionArtifact(store).execute()

        self.assertEqual(result['artifact_version'], 'journey-projection-artifact-v1')
        self.assertEqual(store.loaded, 1)
        self.assertEqual(store.replaced, [])

    def test_load_failure_is_actionable(self):
        with self.assertRaisesRegex(ProjectionArtifactError, 'missing'):
            LoadProjectionArtifact(SpyArtifactStore()).execute()


    def test_refresh_reuses_compatible_transform_when_neighbour_policy_changes_fingerprint(self):
        repo = FakeExplorerRepository((track('a'), track('b', bpm=130, arousal=1.0)))
        prepared = PrepareProjectionArtifact(repo, SpyArtifactStore()).execute().artifact
        import music_analyzer.application.use_cases.projection_artifacts as module
        current = module.NEIGHBOUR_POLICY_VERSION
        try:
            module.NEIGHBOUR_POLICY_VERSION = 'bounded-symmetric-neighbours-v1'
            old_fingerprint = module._fingerprint(*repo.candidate_snapshot(), module.ProjectionParameters(k=10))
        finally:
            module.NEIGHBOUR_POLICY_VERSION = current
        prepared['policy_versions'] = dict(prepared['policy_versions'])
        prepared['policy_versions']['neighbour_policy_version'] = 'bounded-symmetric-neighbours-v1'
        prepared['fingerprint'] = old_fingerprint
        store = SpyArtifactStore(existing=prepared)

        refreshed = RefreshProjectionArtifact(repo, store).execute().artifact

        self.assertEqual(refreshed['transform']['policy_version'], 'anchor-distance-projection-v1')
        self.assertNotEqual(refreshed['fingerprint'], old_fingerprint)
        self.assertEqual(refreshed['policy_versions']['neighbour_policy_version'], 'endpoint-local-exact-top-k-neighbours-v2')

    def test_refresh_preserves_unchanged_coordinates_with_same_transform(self):
        repository = FakeExplorerRepository((track('a'), track('b', bpm=130, arousal=1.0)))
        store = SpyArtifactStore()
        original = PrepareProjectionArtifact(repository, store).execute().artifact
        refreshed = RefreshProjectionArtifact(repository, store).execute().artifact

        before = {point['track_id']: (point['x'], point['y']) for point in original['tracks']}
        after = {point['track_id']: (point['x'], point['y']) for point in refreshed['tracks']}
        self.assertEqual(after, before)
        self.assertEqual(refreshed['transform']['anchors'], original['transform']['anchors'])

    def test_refresh_reconstructs_transform_from_serialized_artifact(self):
        repository = FakeExplorerRepository((track('a'), track('b', bpm=130, arousal=1.0)))
        store = SpyArtifactStore()
        original = PrepareProjectionArtifact(repository, store).execute().artifact
        serialized_existing = {key: value for key, value in original.items() if key != 'transform_object'}
        store.existing = serialized_existing
        refreshed = RefreshProjectionArtifact(repository, store).execute().artifact

        before = {point['track_id']: (point['x'], point['y']) for point in original['tracks']}
        after = {point['track_id']: (point['x'], point['y']) for point in refreshed['tracks']}
        self.assertEqual(after, before)
        self.assertEqual(refreshed['transform']['anchors'], original['transform']['anchors'])

    def test_explicit_relayout_refits_transform(self):
        repository = FakeExplorerRepository((track('a'), track('b', bpm=130, arousal=1.0)))
        store = SpyArtifactStore()
        original = PrepareProjectionArtifact(repository, store).execute().artifact
        changed_repository = FakeExplorerRepository((track('a', bpm=90), track('b', bpm=130, arousal=1.0), track('c', bpm=200)))
        relayout = RefreshProjectionArtifact(changed_repository, store).execute(explicit_relayout=True).artifact

        self.assertNotEqual(relayout['fingerprint'], original['fingerprint'])
        self.assertEqual(relayout['transform']['parameters']['explicit_relayout'], True)


if __name__ == '__main__':
    unittest.main()
