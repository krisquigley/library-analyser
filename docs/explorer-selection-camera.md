# Explorer selected-node camera focus (issue #70, PR6)

Selection focus is an outward browser/ForceGraph concern. It does not change
application/domain policy, graph topology, persistence, filters, or detail-fetch
ownership. Both packaged `app.js` copies remain mirrored.

A selected positioned node is eligible only when it is visible in the current
filtered graph and has finite, non-origin display coordinates. Initial graph
framing precedes animated selection focus. If selection changes before the graph
is available, only the latest authoritative selection may focus. A consumed
focus must not steal manual orbit on subsequent animation frames, mood-only
renders, or resize. The focus uses a bounded 100-display-unit radial offset and
700 ms duration; this is not a viewport/FOV-calibrated scale guarantee.
Hidden, missing, unpositioned, origin, and nonfinite nodes do not trigger a camera
jump; in particular, selection does not clear filters to expose a hidden node.
Reset and authoritative selection reconciliation supersede pending intent.
Selected-node halo behavior and graph-independent detail feedback are preserved.

## Reproducible boundary tests

Require Node on PATH (do not count a Node-dependent skip as acceptance), then run:

```sh
command -v node
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  tests.acceptance.test_explorer_selection_camera_geometry \
  tests.acceptance.test_explorer_selection_camera_integration
```

These tests load both complete assets into isolated Node VMs, exercise real
selection/render methods with fake DOM, camera, scene, frame and HTTP boundaries,
and assert finite display-coordinate camera calls, positive animation duration,
latest-intent ordering, halo and no-jump controls. They do not run a browser or
render WebGL. The handed-off RED commit reproduced six missing-focus scenarios
on both assets (12 assertion failures), without fixture errors; preservation
controls already passed at RED.

## Evidence limitations

Camera-call assertions are not proof of a useful real viewport, perceived smooth
motion, final visible scale, or measured focus latency. Playwright/Chromium was
unavailable during delivery; those real-browser checks remain unverified. No
private library, live selection endpoint, database mutation, performance claim,
or completion of all issue #70 acceptance is implied by this PR.
