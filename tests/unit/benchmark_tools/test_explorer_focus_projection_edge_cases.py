"""Additional outward geometry contracts; controlled readback, not browser evidence."""
import unittest
from threading import Event
from tools import explorer_browser_diagnostic as diagnostic
from tests.acceptance.test_explorer_browser_focus_usefulness import _ReadbackReplay
from tests.unit.benchmark_tools.test_explorer_focus_projection_observation import _run_readback


class FocusProjectionEdges(unittest.TestCase):
    def test_hidden_parent_excludes_neighbor_context(self):
        result = _run_readback("""
const hidden=new vendor.THREE.Scene();scene.add(hidden);hidden.visible=false;
hidden.add(addNode('public-00001',0,0,0));
""")
        context = result['sample']['focus'].get('context', {})
        self.assertEqual(context.get('neighbors_observed'), 1)
        self.assertEqual(context.get('neighbors_in_frustum'), 0)

    def test_nonfinite_vertex_or_camera_is_unavailable_not_zero(self):
        for setup in ('mesh.geometry.attributes.position.array[0]=NaN;', 'camera.fov=NaN;'):
            with self.subTest(setup=setup):
                projection = _run_readback(setup)['sample']['focus'].get('projection', {})
                self.assertEqual(projection.get('status'), 'unavailable')
                self.assertIsNone(projection.get('mesh', {}).get('diameter_px'))

    def test_selected_hidden_ancestor_cannot_pass_success_gate(self):
        sample = _run_readback('parent.visible=false;')['sample']
        result = diagnostic.observe(_ReadbackReplay(sample), 'http://owned.invalid', Event(), 'pending-then-ready')
        self.assertEqual(result['outcome'], 'invalid_response')
        self.assertEqual(sample['focus']['projection']['status'], 'unavailable')

    def test_wrong_mesh_identity_is_unavailable(self):
        result = _run_readback("mesh.userData.trackId='public-00009';")
        self.assertEqual(result['sample']['focus']['projection']['status'], 'unavailable')
        self.assertIsNone(result['sample']['focus']['projection']['mesh']['diameter_px'])

    def test_missing_halo_mesh_is_unavailable_without_losing_readback(self):
        result = _run_readback('context.selectedNodeHalo.mesh=null;')
        self.assertEqual(result['sample']['focus']['projection']['status'], 'unavailable')
        self.assertIsNotNone(result['sample']['milestones_ms']['graph_post_focus_readback'])

    def test_singular_bound_cannot_pass_success_gate(self):
        sample = _run_readback('camera.position.z=3;camera.near=2;')['sample']
        self.assertIsNone(sample['focus']['projection']['halo']['diameter_px'])
        result = diagnostic.observe(_ReadbackReplay(sample), 'http://owned.invalid', Event(), 'pending-then-ready')
        self.assertEqual(result['outcome'], 'invalid_response')

    def test_missing_node_or_selected_halo_retains_readback(self):
        for setup in ('nodes.length=0;', 'context.selectedNodeHalo=null;'):
            with self.subTest(setup=setup):
                sample = _run_readback(setup)['sample']
                self.assertEqual(sample['focus']['projection']['status'], 'unavailable')
                self.assertIsNotNone(sample['milestones_ms']['graph_post_focus_readback'])

    def test_controls_unbounded_is_distinct_from_unavailable(self):
        observed = _run_readback()['sample']['focus']['projection']['controls']
        self.assertEqual(observed['max_distance_status'], 'unbounded')
        self.assertIsNone(observed['max_distance'])
        self.assertIs(observed['enabled'], True)

    def test_unknown_or_invalid_bounds_are_not_labeled_permissive(self):
        for setup in ('controls.minDistance=NaN;controls.maxDistance=undefined;',
                      'controls.minDistance=-1;controls.maxDistance=Infinity;',
                      'controls.minDistance=0;controls.maxDistance=-1;'):
            with self.subTest(setup=setup):
                observed = _run_readback(setup)['sample']['focus']['projection']['controls']
                self.assertIsNone(observed['restrictive'])
                if 'minDistance=-1' in setup:
                    self.assertIsNone(observed['min_distance'])
                    self.assertEqual(observed['min_distance_status'], 'unavailable')
                if 'maxDistance=-1' in setup:
                    self.assertIsNone(observed['max_distance'])
                    self.assertEqual(observed['max_distance_status'], 'unavailable')
        restrictive = _run_readback('controls.minDistance=200;controls.maxDistance=NaN;')['sample']['focus']['projection']['controls']
        self.assertIs(restrictive['restrictive'], True)
        self.assertIs(_run_readback()['sample']['focus']['projection']['controls']['restrictive'], False)

    def test_unavailable_neighbor_projection_keeps_mounted_count_not_partial_frustum_total(self):
        sample = _run_readback("addNode('public-00001',0,0,0).geometry.attributes.position.array[0]=NaN;")['sample']
        self.assertEqual(sample['focus']['context']['status'], 'unavailable')
        self.assertEqual(sample['focus']['context']['neighbors_observed'], 1)
        self.assertIsNone(sample['focus']['context']['neighbors_in_frustum'])

    def test_unmounted_halo_is_unavailable(self):
        projection = _run_readback('scene.remove(halo);')['sample']['focus'].get('projection', {})
        self.assertEqual(projection.get('status'), 'unavailable')
        self.assertIsNone(projection.get('halo', {}).get('diameter_px'))
