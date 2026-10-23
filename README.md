# feasibility_map

Standalone residence-feasibility map program (refactored from a larger
private research project). It renders five field maps over the Bay Area /
Solano / Napa road network (four per-scene drive-time fields + the combined
solver field) from a single editable data file.

```
python -m feasibility_map                  # render everything (uses caches)
python -m feasibility_map --only LHR,comb  # only these maps (+ _clean twins)
python -m feasibility_map --recompute      # rebuild travel-time fields + pieces
python -m feasibility_map --no-basemap     # no Esri background (offline)
python -m feasibility_map --data my.json   # try an alternative points file
python -m feasibility_map -o test          # all outputs into ./test/ for this run
python -m feasibility_map --run-tests tests  # batch: one output folder per tests/*.json
```

Two equivalent entry points:

```
python run.py                 # from inside this folder (works for any folder name)
python -m feasibility_map     # from the parent directory (folder must be named feasibility_map)
```

## Standalone use (as its own project)

```
pip install -r requirements.txt    # numpy, requests, matplotlib, contextily, Pillow
```

- Everything needed ships in the folder: `tiles/` (16 road tiles fetched once
  from the Overpass API, 155 MB) and `osrm_cache.json` (OSRM calibration
  matrix). `cache/` and `figures/` are regenerable and git-ignored.
- First run rebuilds the road graph + travel-time fields + render pieces
  (a few minutes, fully offline). Later runs are render-only (~2 min for all
  10 PNGs); edit `points.json` to try new ideas.
- The optional Esri background layer needs network on the first run (or pass
  `--no-basemap`); it is cached afterwards.
- Data: road network (c) OpenStreetMap contributors (ODbL), via the Overpass
  API; calibration times from the public OSRM demo server; optional basemap
  (c) Esri.

## Editing points — `points.json`

Everything you'll want to experiment with is in this one file:

| What | Where | Effect |
|---|---|---|
| Crime scene position | `scenes[].ll` | recomputes that scene's field (only that one) |
| Scene window (min) | `scenes[].win` | changes its limit, recomputes that field |
| OSRM calibration waypoint | `scenes[].wp` | links to the local `osrm_cache.json`; omit to run uncalibrated |
| Town position | `towns[].ll` | instant (values re-read at the new marker, render only) |
| Town class | `towns[].tier` | `frontier` (big dot, numbered low) or `reference` (small dot) |
| Suspect position | `suspects[].ll` | instant |
| Suspect class | `suspects[].tier` | must be a key of `colors.suspect`; drives its color/legend |
| Marker drawn elsewhere | `marker_ll` | e.g. an address inside a city (used for the value too) |
| Label position | `label_offset` | `[dx, dy]` in points from the marker; nudger adjusts collisions |
| Map list | `maps` | which keys render to which PNG names |
| Paths | `paths` | tiles dir, OSRM cache, figures dir, report file |

IDs are derived automatically and stay stable on every map: scenes S1..Sn in
file order, towns numbered 1..N alphabetically (frontier first, then
reference), suspects A.. in file order.

What triggers a recompute:

- **move/add/remove a town or suspect, change label offsets/colors** ->
  render-only, immediately fast.
- **move a scene or change its window** -> that scene's Dijkstra re-runs
  (seconds); other scenes are reused from `cache/fields.npz`. The render
  pieces are then rebuilt once (~1-2 min) because the fields changed.
- **`--recompute`** -> all fields + pieces rebuilt (a few minutes).
- **tiles change on disk** -> the road graph rebuilds automatically.

## Timeline chains — `events` and `chains`

Optional sections that turn the case timeline into physical checks. The run
log and every figure report print drive time vs the available gap with
PASS/FAIL (verification only — chains do not constrain the fields).

- `events`: named waypoints with metadata, e.g. the phone booths and letter
  drops. `waypoint` must be a name from `osrm_cache.json` (`BRS_phone`,
  `Napa_phone`, `drop_InnerRichmond`, ...); `t`, `kind`, `note` are free text.
- `chains`: `{"from": ..., "to": ..., "gap_min": ...}` — the time available
  between two timed points, plus the physical drive between the endpoints.

Endpoint resolution, by name:

1. scene key (`LHR`, `BRS`, ...) -> the scene's OSRM waypoint
2. event key (`brs_call`, ...) -> the event's `waypoint`
3. OSRM waypoint name -> itself (drive from the cached `wp_matrix`)
4. town name as `from` + scene key as `to` -> the calibrated graph value
   (drive from the town's displayed marker to the scene)

Anything else prints `n/a` with the reason (e.g. cache missing), never
silently skipped. Example (test 12): `{"from": "China Camp Faire",
"to": "Berryessa", "gap_min": 95}` -> drive 106.0 min, FAIL (Kobek-strict;
the same leg at gap 150 passes).

## Caches

`cache/` holds the staged caches; delete a file to force its stage to rebuild:

| File | Contents |
|---|---|
| `graph.npz`, `graph_meta.json` | road graph (rebuilt when a tile file changes) |
| `fields.npz`, `fields_meta.json` | per-scene calibrated travel times |
| `pieces.npz`, `pieces_meta.json` | render pieces (geometry + per-map values) |
| `basemap.png`, `basemap_meta.json` | Esri background layer |
| `report.txt` | full run log (calibration tables, values, layout checks) |

The package is self-contained: road tiles live in `tiles/` (155 MB) and
`osrm_cache.json` is the calibration matrix; both are committed. The
graph/fields/pieces caches are path-independent, so the whole folder can be
moved or copied anywhere and will still run from its caches.

## Testing variants (separate output folders)

`-o DIR` (or `--outdir DIR`) sends the PNGs, their per-figure reports and the
run log into DIR instead of `figures/` + `cache/report.txt`, so different
experiments never overwrite each other:

```
python -m feasibility_map -o test1                       # -> feasibility_map/test1/
python -m feasibility_map --data alt.json -o test2\run   # nested folders are fine
```

DIR is created if needed; relative paths resolve against `points.json` (the
package folder). The graph/fields/pieces caches in `cache/` stay shared and
content-keyed, so switching between variants only recomputes what changed.
`test*/` folders are git-ignored (outputs are regenerable).

## Batch tests (`--run-tests FOLDER`)

`--run-tests FOLDER` treats every `FOLDER/*.json` as a partial override of the
base points file (`--data`, default `points.json`) and gives each test its own
output folder automatically. Overrides merge one level deep: dict-valued keys
(`constants`, `colors`, `paths`) merge key-by-key; lists (`suspects`, `towns`,
`scenes`, ...) and scalars replace whole. A whole test is usually a few lines:

```
tests/
  lower_limit.json     {"constants": {"limit": 30}}
  doerr_only.json      {"suspects": [ ...one entry... ]}
```

```
python -m feasibility_map --run-tests tests --only LHR   # quick pass over all tests
```

Outputs go to `tests/<name>/` (PNGs, per-figure reports, run log) — or
`OUTDIR/<name>/` when `-o` is given. All other flags (`--only`, `--recompute`,
`--no-basemap`, ...) apply to every test; the shared `cache/` is reused
(town/suspect-only tests render in seconds). A broken test is reported as
`FAILED` while the rest continue (exit code 1 when anything failed). Each
test's per-figure report records both the base data file and the test file
with their md5s.

## Outputs

Written to `figures/`: `fig13_feasibility_field.png`, `fig13_brs_field.png`,
`fig13_berryessa_field.png`, `fig13_stine_field.png`,
`fig13_combined_field.png`, plus a `_clean` variant of each (numbered badges
+ right-hand key panel instead of on-map labels). When used inside the larger
research project, copy a finished render into
`zodiackillerinvestigation/figures/` (same file names) to update the write-up.

Every map also gets a `<png base>_report.txt` next to its PNGs — a
per-figure simulation report: what was simulated, the scene geometry, road
network totals, the calibration fit and OSRM cross-check for that scene,
coverage counts, the place values as displayed, the standing caveats, and
(for the LHR map) the period-speed sensitivity. The report is written after
both variants render, so it always matches the PNGs beside it.

If a save fails with `Access denied` / `Errno 22` (some Windows viewers,
antivirus or cloud-sync tools hold freshly written PNGs), the program retries
for about a minute, then skips that one map and reports `FAILED` while the
rest continue. Close whatever is displaying the file and re-run to fill it in.

## Method (unchanged from the original script)

- OSM drivable ways (motorway..residential) from Overpass in 4x4 cached tiles.
- Directed graph (oneway respected), free-flow speed by road class, Dijkstra
  from each scene; times calibrated per scene against the OSRM candidate
  matrix from the local `osrm_cache.json` (mean ratio over the frontier towns).
- Per-scene drive limit = L + window - overhead (77/79/86/81 for L=75).
  Combined field: `min_L = max_i(drive_i - window_i) + overhead`, red at 75.
- Roads drawn as pieces <= 220 m in 24 gamma-warped color bands; red at the
  map's limit, black beyond; caveats in `cache/report.txt`.
