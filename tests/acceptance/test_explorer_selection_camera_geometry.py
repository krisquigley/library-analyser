"""Pure geometry controls for PR6's camera integration tests.

The existing graphCameraFrame API frames a supplied layout, not a selection and
not an animation. These controls deliberately do not invent a focus API or
claim that framing an empty layout should implement selection cancellation.
Selection eligibility, ordering and positive animation duration are covered at
the camera adapter boundary in test_explorer_selection_camera_integration.
"""
import subprocess
import unittest
from pathlib import Path
from tests.support.explorer_app_bundle import explorer_app_script


ROOT = Path(__file__).resolve().parents[2]
APPS = tuple(
    explorer_app_script(ROOT / package / 'frameworks/explorer/assets/app.js')
    for package in ('music_explorer', 'music_analyzer')
)


class SelectionCameraGeometryTests(unittest.TestCase):
    def run_geometry(self, script):
        # Missing Node is a failed prerequisite, not silently passing evidence.
        for app in APPS:
            with self.subTest(app=str(app)):
                result = subprocess.run(
                    ['node', '-e', "const assert=require('node:assert/strict'); "
                     "const app=require(process.argv[1]);\n" + script, str(app)],
                    capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_single_node_frame_targets_display_not_native_axis_coordinates(self):
        self.run_geometry(r'''
const graph={positioned:[{
  track_id:'selected',display_label:'Selected',bpm:123,genres:[],
  x:{raw:0.25,normalized:0.75},
  y:{raw:0.4,normalized:0.5},
  z:{raw:123,normalized:12.3}
}],edges:[],unpositioned:[]};
const model=app.buildMoodGraphModel(graph);
const before=JSON.stringify(model);
const node=model.nodes[0];
const frame=app.graphCameraFrame([node],{width:800,height:600},50);
assert.deepEqual(frame.target,{x:270,y:180,z:4428});
assert.deepEqual(frame.target,{x:node.fx,y:node.fy,z:node.fz});
assert.notEqual(frame.target.z,node.axis.z.raw);
assert(Object.values(frame.position).every(Number.isFinite));
assert(frame.position.z>frame.target.z,'single-node camera must not coincide with its target');
assert.equal(JSON.stringify(model),before,'framing must preserve fixed coordinates and native axes');
''')

    def test_origin_frame_has_finite_nonzero_camera_offset(self):
        self.run_geometry(r'''
// Origin is a valid layout coordinate for framing. Whether a selection at the
// origin is focus-eligible belongs to the adapter, not this existing pure API.
for(const size of [{width:800,height:600},{width:0,height:0}]){
  for(const fov of [50,NaN,0,180]){
    const frame=app.graphCameraFrame([{id:'origin',x:0,y:0,z:0}],size,fov);
    assert.deepEqual(frame.target,{x:0,y:0,z:0});
    assert(Object.values(frame.position).every(Number.isFinite));
    assert(frame.position.z-frame.target.z>=40,'zero-vector layout must not put camera on target');
  }
}
''')

    def test_invalid_coordinates_do_not_shift_available_node_frame(self):
        self.run_geometry(r'''
const valid={id:'available',x:-90,y:120,z:4500};
const size={width:800,height:600};
const expected=app.graphCameraFrame([valid],size,50);
for(const axis of ['x','y','z']){
  for(const value of [NaN,Infinity,-Infinity,undefined,null,'0']){
    const invalid={id:'invalid',x:1,y:2,z:3,[axis]:value};
    assert.deepEqual(app.graphCameraFrame([invalid,valid],size,50),expected);
    const fallback=app.graphCameraFrame([invalid],size,50);
    assert(Object.values(fallback.position).every(Number.isFinite));
    assert(Object.values(fallback.target).every(Number.isFinite));
  }
}
''')
