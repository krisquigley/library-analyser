# Chained energy arc pilot

`tools/playlist_arc_pilot.py` measures how closely generated playlists follow a chain of energy arcs (#137). It
runs the playlist preview (#138) from a seeded sample of eligible start tracks, so it walks exactly as the M3U download
would, and reports aggregates only.

```bash
python -m tools.playlist_arc_pilot --database "$DB" --chain rise:10,fall:10,peak:10 \
    --bpm-min 100 --bpm-max 140 --starts 30 --weights 0.6,0.8
```

- `--chain` is `shape:length,...` in order; `--unit minutes` reads the lengths as minutes (default: tracks).
- `--weights` repeats the runs at each arc weight, to re-check the weight on chains. The override exists only for the
  pilot's runs and is put back afterwards; the Explorer always uses the weight in `music_explorer/domain/energy_plan.py`.
- `--seed` fixes the sample of start tracks, so runs are repeatable.

For each weight it reports, per arc, the tracks placed, how many have known energy, and the mean distance between the
arc's target and the energy level actually placed (both ranks among the eligible tracks, 0–1). It also reports the mean
relation score of the transitions, the number of runs, incomplete runs and failed starts, and the run time p50/p95/max
in seconds. These are descriptive values, never budgets.

**Privacy.** The database is opened read-only. The report names no track, title, artist or path. Share only the
aggregate report, as AGENTS.md requires.
