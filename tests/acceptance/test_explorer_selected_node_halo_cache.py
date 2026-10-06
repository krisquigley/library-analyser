"""Selected-node halo cache lifecycle, exercised with Node without a browser."""
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ASSET_PATHS = (
    ROOT / 'music_explorer' / 'frameworks' / 'explorer' / 'assets' / 'app.js',
    ROOT / 'music_analyzer' / 'frameworks' / 'explorer' / 'assets' / 'app.js',
)


class SelectedNodeHaloCacheTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node required for browser model tests')
    def test_stable_selection_reuses_cached_mesh_without_scene_walk_and_tracks_live_position(self):
        script = r'''
const assert = require('assert');
const {syncSelectedNodeHalo,setStateForTesting} = require(process.argv[1]);
let childReads = 0;
class Geometry { constructor(radius){ this.radius = radius; } dispose(){ this.disposed = true; } }
class Material { constructor(props){ this.props = props || {}; } dispose(){ this.disposed = true; } }
class Mesh {
  constructor(geometry, material){
    this.geometry = geometry;
    this.material = material;
    this.userData = {};
    this.position = {x:0,y:0,z:0,set(x,y,z){ this.x = x; this.y = y; this.z = z; }};
    this.scale = {x:1,y:1,z:1,setScalar(value){ this.value = value; }};
  }
}
class Branch {
  constructor(children = []){ this._children = children; for(const child of children) child.parent = this; }
  get children(){ childReads += 1; return this._children; }
  add(child){ this._children.push(child); child.parent = this; }
  remove(child){ this._children = this._children.filter(c => c !== child); child.parent = null; }
}
class Scene extends Branch {}
const selectedNode = {id:'track-a', x:1, y:2, z:3, color:'#123456'};
const nodeMesh = new Mesh(new Geometry(4), new Material({}));
nodeMesh.userData = {trackId:'track-a'};
nodeMesh.position.set(10, 20, 30);
const branch = new Branch([nodeMesh]);
const scene = new Scene([branch]);
const graph = {scene: () => scene};
setStateForTesting({current_track_id:'track-a'});
const first = syncSelectedNodeHalo(graph, {nodes:[selectedNode], links:[]});
assert(first, 'first sync creates a halo');
assert.equal(first.position.x, 10);
assert.equal(first.position.y, 20);
assert.equal(first.position.z, 30);
assert.equal(first.material.props.depthTest, false, 'halo stays visible through dense graph nodes');
const readsAfterFirstDiscovery = childReads;
nodeMesh.position.set(40, 50, 60);
const second = syncSelectedNodeHalo(graph, {nodes:[selectedNode], links:[]});
assert.strictEqual(second, first, 'stable selected graph reuses the existing halo');
assert.equal(childReads, readsAfterFirstDiscovery, 'stable RAF sync must not recursively walk scene.children again');
assert.equal(second.position.x, 40, 'cached mesh position remains live');
assert.equal(second.position.y, 50);
assert.equal(second.position.z, 60);
branch.remove(nodeMesh);
const replacement = new Mesh(new Geometry(5), new Material({}));
replacement.userData = {trackId:'track-a'};
replacement.position.set(70, 80, 90);
branch.add(replacement);
const afterUnmount = syncSelectedNodeHalo(graph, {nodes:[selectedNode], links:[]});
assert.notStrictEqual(afterUnmount, first, 'unmounted cached mesh invalidates the halo instead of retaining stale objects');
assert.equal(afterUnmount.position.x, 70);
assert.equal(afterUnmount.position.y, 80);
assert.equal(afterUnmount.position.z, 90);
afterUnmount.disposed = true;
const afterStaleHalo = syncSelectedNodeHalo(graph, {nodes:[selectedNode], links:[]});
assert.notStrictEqual(afterStaleHalo, afterUnmount, 'disposed cached halo is not retained');
assert.equal(afterStaleHalo.position.x, 70);
'''

        for asset in ASSET_PATHS:
            with self.subTest(asset=str(asset.relative_to(ROOT))):
                result = subprocess.run(['node', '-e', script, str(asset)], capture_output=True, text=True, cwd=ROOT)
                self.assertEqual(result.returncode, 0, result.stderr)
