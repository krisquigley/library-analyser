# Explorer selected-node camera focus (issue #70, PR6)

Selection focus is an outward browser/ForceGraph concern. It does not change
application/domain policy, graph topology, persistence, filters, or detail-fetch
ownership. Both packaged `app.js` copies remain mirrored.

A selected positioned node is eligible only when it is visible in the current
filtered graph and has finite display coordinates, including the origin. Initial
graph framing precedes animated selection focus. If selection changes before the graph
is available, only the latest authoritative selection may focus. A consumed
focus must not steal manual orbit on subsequent animation frames, mood-only
renders, or resize. The focus uses a nominal 100-display-unit radial offset and
700 ms duration. The configured orbit-controls `minDistance` and `maxDistance`
bounds take precedence: the endpoint radius is 100 only when those bounds permit
it, otherwise it is clamped to the configured interval. Bounds-compatible
ordinary starting poses retain a smooth in-range radius throughout the transition,
without changing the configured bounds or relying on a later controls update to
snap the endpoint into range. This is not a viewport/FOV-calibrated scale guarantee.
For an origin node, the undefined radial direction falls back to the current
viewing direction (or a deterministic nonzero direction), preserving a finite,
nondegenerate focus. Hidden, missing, unpositioned, and nonfinite nodes do not
trigger a camera jump; selection does not clear filters to expose a hidden node.
While an existing graph's replacement request or render is pending, retain only
the latest accepted focus and reconcile it after the replacement graph is
rendered. Do not consume it against the old layout. Once the new graph is
rendered, discard a genuinely hidden/missing/unpositioned selection normally.

Finite camera components do not guarantee a finite radius or safe bundled
Trackball arithmetic. Astronomical starting offsets use scaled direction
normalization and bounded finite recovery before interpolation, retaining a
usable up vector. Recovery also rebases the starting orbit target to the origin:
a small focus offset is not representable beside an astronomical panned target.
The recovery radius uses the same bounds-compatible nominal focus distance.
This exceptional recovery is not a promise of continuous motion across
astronomical distances; ordinary poses retain the smooth camera-relative arc
and the same bounded radial endpoint. At 700 ms both position and look-at target use
the exact selected-node endpoint, avoiding large-start interpolation cancellation.

Reset, history/new-selection intent, and changed authoritative selection
reconciliation supersede active motion as well as pending intent. User orbit
cancels active motion; an accepted focus deferred for a replacement graph still
reconciles after that graph is rendered. The bundled
ForceGraph camera API has no public tween-cancellation method: its timed
`cameraPosition` creates private position and look-at tweens, and a zero-duration
setter does **not** cancel those tweens. Consequently, focus animation belongs
to the delivery adapter: a bounded requestAnimationFrame transition writes
through `cameraPosition(position, target, 0)` and owns cancellation. It never
starts vendor tweens, so no private vendor state or vendor modification is
needed. Both camera position and orbit-controls target stop moving when the
transition is cancelled; controls' `start` event yields ownership to user orbit.
Selected-node halo behavior and graph-independent detail feedback are preserved.

Mouseup can leave rotation, wheel and pan damping pending in the bundled Trackball
controls; `enabled = false` does not prevent their public `update()` from applying
it, and disabling rotation during settlement leaves its inertia untouched.
When focus takes ownership, the adapter drains those pending inputs with one
bounded public update: temporarily enable all three inputs, use zero rotate/zoom/pan
speeds and full dynamic damping (`staticMoving = false`, `dynamicDampingFactor = 1`)
on an overflow-safe finite pose, then restore the starting pose and all changed
public settings, including rotation speed, damping and distance bounds. This preserves
ordinary starting position, target, up vector, orientation, radius and configured
distance bounds without accessing private control state,
modifying the vendor bundle or iterating until damping converges. Later manual
orbit still owns cancellation and uses the original controls settings.

The bundled zero-duration `cameraPosition` setter updates the controls target
only while controls are enabled; when disabled it updates the camera's look-at
orientation instead. The delivery adapter synchronizes the public controls target
explicitly for focus writes, including settlement and pose restoration, while
preserving `controls.enabled`. Disabled controls therefore retain the selected-node
target through completion, and re-enabling them does not jump back to a stale orbit
target. This is separate from draining damping: ForceGraph's normal tick skips
controls updates when disabled, but Trackball's public `update()` itself does not.

## Reproducible boundary tests

Require Node on PATH (do not count a Node-dependent skip as acceptance), then run:

```sh
command -v node
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  tests.acceptance.test_explorer_selection_camera_geometry \
  tests.acceptance.test_explorer_selection_camera_integration \
  tests.acceptance.test_explorer_selection_camera_cancellation \
  tests.acceptance.test_explorer_camera_vendor_cancellation \
  tests.acceptance.test_explorer_camera_orbit_path \
  tests.acceptance.test_explorer_camera_unflushed_damping \
  tests.acceptance.test_explorer_camera_disabled_controls \
  tests.acceptance.test_explorer_camera_custom_bounds \
  tests.acceptance.test_explorer_3d_graph_assets.Explorer3DGraphAssetTests.test_graph_camera_centers_bounds_fits_viewport_and_preserves_selection_view \
  tests.architecture.test_import_boundaries
```

These tests load both complete assets into isolated Node VMs and exercise real
selection/render methods with controlled DOM, scene, frame and HTTP boundaries.
They assert finite display-coordinate geometry, intermediate motion and final
focus, latest-intent ordering, halo and no-jump controls. Cancellation regressions
advance a controlled clock past the old animation deadline, including unresolved
selection/reset POSTs and manual orbit. The vendor-boundary tests evaluate the
actual bundled THREE/TWEEN implementation and unchanged `cameraPosition` method
via test-only closure exports; they also prove that an instantaneous vendor call
alone cannot cancel existing vendor tweens. Those exports modify only the
in-memory test source; packaged vendor files are unchanged. The harness fails
explicitly if the pinned bundle's extraction boundary changes.

Fresh remediation reproduced the existing-instance reload defect and stale
camera/target motion before production fixes. The rotation regression also performs
an actual bundled left drag and mouseup immediately before selection, then advances
16 ms control updates through 1200 ms (including the exact 700 ms endpoint). It
checks stable position, target, up and quaternion after completion, supersession,
restored public settings and a fresh dynamic manual orbit after focus. Disabled
controls regressions also use the actual bundled camera setter and Trackball
controls, check settlement/restoration and intermediate target writes, then
re-enable controls and verify stable position, up and quaternion. Custom-bound
regressions cover a minimum above 100 and a maximum below 100, checking in-range
motion, the bounds-compatible endpoint and stable later control updates. Existing
unflushed wheel/pan regressions remain in place. These are deterministic
API-boundary regressions, not a browser render or measured WebGL result.

## CI command inventory

The required `.github/workflows/ci.yml` job uses Python 3.14 on Ubuntu 24.04 and
runs these commands in order. The full-suite environment flags disable the opt-in
decode and packaging suites; they do not disable every packaging test. The
unconditional distribution-metadata compatibility test still invokes
`python -m pip wheel`, so the full suite requires an available `pip`:

```sh
python -m unittest discover -s tests/unit -v
python -m unittest tests.architecture.test_import_boundaries -v
RUN_FFMPEG_TESTS=0 RUN_PACKAGING_TESTS=0 python -m unittest discover -v
python -m pip install setuptools==84.0.0
```

The last command installs build tooling only; it does not run a wheel build or
installation acceptance test. A separate opt-in workflow-dispatch job requires
runner-provided FFmpeg and runs:

```sh
ffmpeg -version
RUN_FFMPEG_TESTS=1 python -m unittest tests.integration.infrastructure.test_audio_decode -v
```

Focused camera regressions require an actual Node runtime. For remediation runs,
use a hard SIGKILL timeout for each Node process (including vendor wheel loops),
not just a timeout that can leave a subprocess alive; record the runtime version
and any full-suite skips separately from the focused no-skip results.

## Evidence limitations

Camera-call assertions are not proof of a useful real viewport, perceived smooth
motion, final visible scale, or measured focus latency. Playwright/Chromium was
unavailable during delivery; those real-browser checks remain unverified. No
private library, live selection endpoint, database mutation, performance claim,
or completion of all issue #70 acceptance is implied by this PR.
