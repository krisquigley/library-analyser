#!/bin/bash
# In-container half of tools/explorer_browser_gate.py. Arguments: DEADLINE MODULE...
# Writes only text evidence to /evidence; all scratch is tmpfs and is discarded.
set -u
E=/evidence
DEADLINE=$1; shift
ulimit -c 0
blocked() { echo "$1" > "$E/blocked.txt"; exit 2; }
cgroup() {
  for f in memory.max memory.swap.max memory.oom.group; do echo "$f=$(cat /sys/fs/cgroup/$f 2>/dev/null)"; done
}
cgroup > "$E/cgroup-before.txt"
(cd /wheelhouse && sha256sum --quiet -c SHA256SUMS) >/dev/null 2>&1 || blocked 'wheelhouse checksum'
python3 -m pip install -q --root-user-action=ignore --no-index --find-links /wheelhouse --target /site \
  music_analyzer playwright >/dev/null 2>&1 || blocked 'offline install'

# tools/ and tests/ come from the checkout; the product comes from the wheel.
# explorer_browser_routes serves <tools>/../music_explorer/.../assets and its
# traversal guard rejects symlinks, so copy the installed assets there (no
# __init__.py, and /site precedes /work, so imports still resolve to /site).
mkdir -p /work/music_explorer/frameworks/explorer
cp -r /suite/tests /suite/tools /work/
cp -r /site/music_explorer/frameworks/explorer/assets /work/music_explorer/frameworks/explorer/
diff -r /site/music_explorer/frameworks/explorer/assets /work/music_explorer/frameworks/explorer/assets \
  >/dev/null || blocked 'installed assets copy differs'
# test_explorer_xyz_axes launches /usr/bin/chromium explicitly.
CHROME=$(ls -d /ms-playwright/chromium-*/chrome-linux*/chrome 2>/dev/null | head -1)
[ -x "$CHROME" ] || blocked 'pinned Chromium missing from image'
ln -sf "$CHROME" /usr/bin/chromium || blocked 'cannot link /usr/bin/chromium'

export PYTHONPATH=/site:/work PYTHONDONTWRITEBYTECODE=1
export TMPDIR=/scratch XDG_CONFIG_HOME=/bscratch/config XDG_CACHE_HOME=/bscratch/cache HOME=/bscratch/home
export EXPLORER_INSTALLED_WHEEL_ROOT=/site
export EXPLORER_INSTALLED_ASSETS=/site/music_explorer/frameworks/explorer/assets
export EXPLORER_FOCUS_EVIDENCE_DIR=/scratch/focus-evidence
mkdir -p "$XDG_CONFIG_HOME" "$XDG_CACHE_HOME" "$HOME"
cd /scratch || blocked 'scratch unavailable'
python3 -c 'import music_explorer.frameworks.explorer.server as s, sys; sys.exit(not s.__file__.startswith("/site/"))' \
  || blocked 'music_explorer does not import from the installed wheel'

for module in "$@"; do
  timeout --signal=KILL "$DEADLINE" python3 -m unittest -v "tests.acceptance.$module" > "$E/$module.log" 2>&1
  echo $? > "$E/$module.rc"
done
cgroup > "$E/cgroup-after.txt"
cat /sys/fs/cgroup/memory.events > "$E/memory-events-after.txt" 2>/dev/null
echo "peak_bytes=$(cat /sys/fs/cgroup/memory.peak 2>/dev/null)" >> "$E/cgroup-after.txt"
