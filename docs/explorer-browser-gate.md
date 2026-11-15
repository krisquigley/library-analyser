# Explorer Chromium browser gate

`tools/explorer_browser_gate.py` runs the formal Explorer browser acceptance
modules in real Chromium. It runs them against the **installed wheel** built
from your working tree, under a Podman resource supervisor. This is the gate
#88 refers to. It is a correctness gate, not a performance measurement:
latency and throughput budgets are not asserted.

## Run it

From the repository root:

```sh
python -m tools.explorer_browser_gate prepare --wheelhouse /path/to/new/wheelhouse   # network
python -m tools.explorer_browser_gate run --wheelhouse /path/to/new/wheelhouse \
    --evidence /path/to/new/evidence [--module test_explorer_browser_smoke ...]
```

- **`prepare`** does three things:
  - builds `music_analyzer` from the working tree;
  - downloads the pinned `playwright==1.65.2`, its `greenlet`, and `mutagen` for the image's Python 3.12;
  - writes `SHA256SUMS`.
- **`run`** needs only Podman and no network.

**Exit codes:** `0` PASS, `1` FAIL, `2` BLOCKED.

## Requirements

- **Podman**, rootless with cgroup v2 is fine. There is no Docker fallback: without Podman the gate is BLOCKED.
- The digest-pinned image `mcr.microsoft.com/playwright/python:v1.65.2-noble`. It provides Chromium (WebGL2 via SwiftShader), Python 3.12 and SQLite 3.45.

## Supervisor

`run` starts one container. Its limits are pinned by
`tests/unit/benchmark_tools/test_explorer_browser_gate.py`:

| Bound | Setting |
| --- | --- |
| Memory | `memory.max` 4 GiB, `memory.swap.max` 0, `memory.oom.group` 1 (read inside, before and after) |
| Isolation | `--network none`, private cgroup namespace, `--rm` (owned descendants are reaped) |
| Dumps and files | core dumps off; per-file size ≤ 512 MiB |
| Scratch | fixtures/`TMPDIR` on a 1 GiB tmpfs; `XDG_CONFIG_HOME`/`XDG_CACHE_HOME` on a 128 MiB tmpfs |
| Deadlines | 900 s per module (`SIGKILL`), and a total deadline that force-removes the container |

The image digest and wheel checksums are verified before anything runs.
`tests/` and `tools/` are mounted read-only from the checkout. The product
(`music_analyzer`, `music_explorer`) imports from the installed wheel.

## Results

- **PASS:** the module ran at least one test and every non-skipped test passed.
- **SKIP:** every test in the module skipped.
- **FAIL:** a test failed, a deadline was hit, the module did not run, or an OOM kill occurred.
- **BLOCKED:** a prerequisite is missing, so no verdict was possible. Causes: no Podman, a wheelhouse checksum mismatch, an offline install failure, the product not importing from the wheel, or supervisor limits that were not applied.

Designed skips:
- the ~41 MiB stress profile, which needs separate approval and is never enabled here;
- two Node-only model tests in `test_explorer_xyz_axes`, which run in the normal host suite.

The evidence directory keeps only:
- per-module unittest logs and exit codes;
- the cgroup readings and `memory.events`;
- `summary.json`, with the commit, a source-dirty flag, the image and the wheel checksums.

Screenshots, HAR files, response bodies, dumps and focus JSON stay on tmpfs and are discarded.

## Notes

- `tools/explorer_browser_routes.py` serves UI assets from
  `<tools>/../music_explorer/.../assets`. The container copies the installed
  assets there and verifies they are identical. A symlink would be rejected by
  the route's traversal guard.
- `test_explorer_xyz_axes` launches `/usr/bin/chromium`. The container links it
  to the image's pinned Chromium.
