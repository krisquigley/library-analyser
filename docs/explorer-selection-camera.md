# Explorer selected-node camera focus (issue #70, PR6)

Selection focus is an outward browser/ForceGraph concern. It does not change
application/domain policy, graph topology, persistence, filters, or detail-fetch
ownership. Both packaged `app.js` copies remain mirrored.

A selected positioned node is eligible only when it is visible in the current
filtered graph and has finite display coordinates, including the origin. Initial
graph framing precedes animated selection focus. If selection changes before the graph
is available, only the latest authoritative selection may focus. A consumed
focus must not steal manual orbit on subsequent animation frames, mood-only
renders, or resize. The focus uses a bounded 100-display-unit radial offset and
700 ms duration; this is not a viewport/FOV-calibrated scale guarantee.
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
a 100-unit offset is not representable beside an astronomical panned target.
This exceptional recovery is not a promise of continuous motion across
astronomical distances; ordinary poses retain the smooth camera-relative arc
and the same radial endpoint. At 700 ms both position and look-at target use
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

Mouseup can leave wheel and pan damping pending in the bundled Trackball controls;
`enabled = false` does not prevent their public `update()` from applying it.
When focus takes ownership, the adapter drains those pending inputs with one
bounded public update: temporarily use static motion, zero zoom/pan speeds and
an overflow-safe finite pose, then restore the starting pose and all changed
public settings. This preserves ordinary starting position, target, up vector,
orientation, radius and configured distance bounds without accessing private control state,
modifying the vendor bundle or iterating until damping converges. Later manual
orbit still owns cancellation and uses the original controls settings.

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
camera/target motion before production fixes. These are deterministic API-boundary
regressions, not a browser render or measured WebGL result.

## Evidence limitations

Camera-call assertions are not proof of a useful real viewport, perceived smooth
motion, final visible scale, or measured focus latency. Playwright/Chromium was
unavailable during delivery; those real-browser checks remain unverified. No
private library, live selection endpoint, database mutation, performance claim,
or completion of all issue #70 acceptance is implied by this PR.
