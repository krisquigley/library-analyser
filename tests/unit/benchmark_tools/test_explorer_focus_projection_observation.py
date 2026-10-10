"""Projected vertex bounds and frustum context contracts, not usefulness bands.

Runs the exact diagnostic readback with real bundled THREE geometry/camera math.
Renderer/readPixels are controlled boundary doubles: this is not browser evidence,
exact raster diameter, occlusion evidence, or a performance measurement.
"""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
from threading import Event
import unittest

from tools import explorer_browser_diagnostic as diagnostic
from tests.acceptance.test_explorer_camera_vendor_cancellation import VENDOR
from tests.acceptance.test_explorer_selection_camera_integration import ASSETS


class _ReadbackCaptured(Exception):
    pass


class _CapturePage:
    def set_default_timeout(self, value): pass
    def add_init_script(self, script): pass
    def goto(self, *args, **kwargs): pass
    def wait_for_function(self, script): pass
    def locator(self, selector): return self
    @property
    def first(self): return self
    def click(self): pass
    def fill(self, value): pass
    def evaluate(self, script):
        if 'gl.readPixels(' in script:
            self.readback = script
            raise _ReadbackCaptured()
        if '.requests.filter' in script:
            return 1
        return None


def _readback_script():
    page = _CapturePage()
    try:
        diagnostic.observe(page, 'http://owned.invalid', Event(), 'pending-then-ready')
    except _ReadbackCaptured:
        return page.readback
    raise AssertionError('diagnostic must reach its actual readback before behavioral RED')


def _node():
    executable = shutil.which('node') or shutil.which('nodejs')
    if executable:
        return executable
    spec = importlib.util.find_spec('playwright')
    if spec and spec.origin:
        bundled = Path(spec.origin).parent / 'driver' / 'node'
        if bundled.is_file():
            return str(bundled)
    raise AssertionError('Node unavailable: prerequisite blocker, not intended RED')


def _run_readback(setup=''):
    """Execute production callback; setup may alter real scene objects/public camera."""
    source = VENDOR + r'''
const THREE=vendor.THREE;
const scene=new THREE.Scene();
const camera=new THREE.PerspectiveCamera(60,800/600,1,100);
camera.position.set(0,0,20); camera.lookAt(0,0,0);
const box={width:800,height:600,left:0,top:0};
const nodes=[];
function addNode(id,x,y,z) {
  const object=new THREE.Mesh(new THREE.SphereGeometry(2,16,12),new THREE.MeshBasicMaterial());
  object.userData.trackId=id; object.position.set(x,y,z); scene.add(object);
  nodes.push({id,x,y,z}); return object;
}
const mesh=addNode('public-00000',0,0,0);
const parent=new THREE.Scene(); scene.add(parent); parent.add(mesh); parent.scale.set(1.5,1,1);
const halo=new THREE.Mesh(new THREE.SphereGeometry(3,16,12),new THREE.MeshBasicMaterial({depthTest:false}));
halo.name='selected-node-halo'; halo.userData.trackId='public-00000'; scene.add(halo);
const controls={target:new THREE.Vector3(),minDistance:0,maxDistance:Infinity,enabled:true};
const gl={RGBA:1,UNSIGNED_BYTE:2,VERSION:3,VENDOR:4,RENDERER:5,
  readPixels(x,y,w,h,format,type,pixels){pixels[4]=255;},getExtension(){return null;},
  getParameter(key){return key===3?'WebGL 1.0':'WebKit';}};
const renderer={domElement:{width:2,height:2,getBoundingClientRect:()=>box},
  render(){scene.updateMatrixWorld(true);camera.updateMatrixWorld(true);},getContext:()=>gl};
function findSceneObject(root,predicate) {
  if(predicate(root))return root;
  for(const child of root.children||[]){const match=findSceneObject(child,predicate);if(match)return match;}
  return null;
}
function graphObjectTrackId(object){return object.userData?.trackId||null;}
const context={console,Uint8Array,performance:{now:()=>10},
  requestAnimationFrame:callback=>{callback(10);return 1;},
  state:{current_track_id:'public-00000'},pendingSelectionOperation:null,renderedGraphData:{nodes,links:[]},
  selectedNodeHalo:{mesh:halo,trackId:'public-00000'},findSceneObject,graphObjectTrackId,
  forceGraph:{scene:()=>scene,camera:()=>camera,controls:()=>controls,renderer:()=>renderer,
    graph2ScreenCoords:()=>({x:400,y:300})},
  __diagnostic:{milestones_ms:{},requests:[],consumed_count:1}};
context.window=context;
SETUP
camera.updateProjectionMatrix(); scene.updateMatrixWorld(true);camera.updateMatrixWorld(true);
// Independent oracle: transform actual vertices, then measure CSS projected bound.
function reference(object) {
  const coordinates=[];const position=object.geometry.attributes.position;
  for(let i=0;i<position.count;i++) {
    const point=new THREE.Vector3().fromBufferAttribute(position,i).applyMatrix4(object.matrixWorld).project(camera);
    coordinates.push([(point.x+1)*box.width/2,(1-point.y)*box.height/2]);
  }
  const xs=coordinates.map(point=>point[0]),ys=coordinates.map(point=>point[1]);
  const width=Math.max(...xs)-Math.min(...xs),height=Math.max(...ys)-Math.min(...ys);
  return {diameter_px:Math.max(width,height),diameter_viewport_fraction:Math.max(width,height)/Math.min(box.width,box.height)};
}
const vm=require('node:vm');vm.createContext(context);
(async()=>{
  const settings=()=>({min_distance:controls.minDistance,max_distance:controls.maxDistance,enabled:controls.enabled});
  const controls_before=settings();
  const sample=await vm.runInContext('('+READBACK+')()',context);
  console.log(JSON.stringify({sample,controls_before,controls_after:settings(),
    reference:{mesh:reference(mesh),halo:reference(halo)}}));
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
'''
    source = source.replace('SETUP', setup).replace('READBACK', json.dumps(_readback_script()))
    result = subprocess.run([_node(), '-e', source, str(ASSETS[0])],
                            capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise AssertionError('readback harness prerequisite failure, not RED: ' + result.stderr)
    return json.loads(result.stdout)


class FocusProjectionObservation(unittest.TestCase):
    def projection(self, result):
        focus = result['sample']['focus']
        self.assertIn('projection', focus,
                      'center and halo attachment do not observe actual projected geometry')
        projection = focus['projection']
        self.assertEqual(projection['status'], 'observed')
        return projection

    def test_actual_mesh_and_halo_projected_vertex_diameters_not_center_only(self):
        for setup in ('', 'halo.scale.setScalar(2);camera.fov=75;camera.position.z=30;'
                      'box.width=600;box.height=800;camera.aspect=600/800;'):
            with self.subTest(setup=setup):
                result = _run_readback(setup)
                projection = self.projection(result)
                self.assertEqual(projection['measurement'], 'projected-vertex-bound')
                for name in ('mesh', 'halo'):
                    for field in ('diameter_px', 'diameter_viewport_fraction'):
                        self.assertAlmostEqual(projection[name][field], result['reference'][name][field], places=6)
                self.assertEqual(projection['viewport']['width_px'], 600 if setup else 800)
                self.assertEqual(projection['viewport']['height_px'], 800 if setup else 600)
                self.assertEqual(projection['camera']['fov_degrees'], 75 if setup else 60)
                self.assertAlmostEqual(projection['camera']['aspect'], 600 / 800 if setup else 800 / 600)
                self.assertEqual(projection['camera']['near'], 1)
                self.assertEqual(projection['camera']['far'], 100)

    def test_center_inside_does_not_conceal_viewport_near_far_or_behind_clipping(self):
        cases = (
            ('halo.scale.setScalar(5);', 'halo', 'viewport'),
            ('camera.position.z=3;camera.near=2;', 'mesh', 'near'),
            ('camera.far=19;', 'mesh', 'far'),
            ('mesh.position.z=25;', 'mesh', 'behind_camera'),
        )
        for setup, name, clipping in cases:
            with self.subTest(clipping=clipping):
                result = _run_readback(setup)
                self.assertTrue(result['sample']['focus']['selected_node_in_view'],
                                'controlled center-only observation stays inside in every case')
                projection = self.projection(result)
                self.assertIs(projection[name]['clipping'][clipping], True,
                              'real geometry clipping must be reported separately from center visibility')

    def test_neighbor_context_counts_measured_scene_frustum_not_graph_model_count(self):
        setup = '''
addNode('public-00001',0,0,0);
addNode('public-00002',1000,0,0);
addNode('public-00003',0,0,30);
addNode('public-00004',0,0,0).visible=false;
nodes.push({id:'public-00005',x:0,y:0,z:0});
context.renderedGraphData.links=[{source:'public-00000',target:'public-00002'}];
'''
        for change, expected in (('', 1), ("scene.children.find(o=>o.userData.trackId==='public-00002').position.x=0;", 2)):
            with self.subTest(expected=expected):
                focus = _run_readback(setup + change)['sample']['focus']
                self.assertIn('context', focus, 'graph membership does not measure surrounding rendered context')
                observed = focus['context']
                self.assertEqual(observed['measurement'], 'frustum-not-occlusion')
                self.assertEqual(observed['neighbors_observed'], 4)
                self.assertEqual(observed['neighbors_in_frustum'], expected)
