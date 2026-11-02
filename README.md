# LUMEN-Crop

Puts AP's 5-arc-minute crop downscale onto the LUMEN 0.25° `pid` grid and rescales it so each
pid's crop area matches LUMEN's `lu_out` crop pool in the base year.

One command, three inputs, two deliverables.

## Run it

```
run.bat
```

That is the whole pipeline (about 30 s). It stops at the first failed check and says which one.
Options are passed straight through, e.g.

```
run.bat --ap input\AP_UGA_downscale.gdx          # a different AP country file
run.bat --baseyear 2025                           # anchor to a different LUMEN year
run.bat --help
```

`run.bat` uses the Python bundled with GAMS 49 (`C:\GAMS\49\GMSPython`), which already has
pandas and `gams.transfer`. Nothing else needs installing. If GAMS lives elsewhere, edit the one
`GAMSDIR` line at the top of `run.bat`.

## Inputs (`input/`)

The LUMEN solution and the Crop Allocation Model country file are private inputs and are not in this repository. Place them in `input/` by hand before running. Only the master grid `PIXEL_TO_DIM.gdx` is tracked.

| file | owner | swap it? | what it is |
|---|---|---|---|
| `solution_lu.gdx` | LUMEN | **yes, every run** | a LUMEN solution: `pid`, `pid_coords`, `pid_run`, `cty_run`, `yrs`, `lu_out` |
| `AP_KEN_downscale_for_ABHI.gdx` | AP | **yes, per country** | `PIXEL_TO_DIM` (its own pixels), `p_Area`, `p_Production` |
| `PIXEL_TO_DIM.gdx` | AP | no, fixed | master 5-arc-min grid: every pixel key → (X, Y) centre, 964,338 pixels |

Drop a new LUMEN solution in as `input/solution_lu.gdx` (any country; the country code is read
from `cty_run` inside it). Drop a new AP file in and point `--ap` at it (or keep the default name).
The master grid stays as it is; it only changes if AP changes their grid.

The AP file carries its own pixel coordinates, so the mapping does not *depend* on the master
grid. The master is used for the global crosswalk deliverable and as a cross-check: every AP
pixel whose key is in the master must have the same coordinates and land in the same pid, or
the run stops.

## Deliverables (`output/`)

**`pixel5min_to_pid025.gdx`** — the general crosswalk, global, independent of the AP country file

| symbol | records (KEN run) | |
|---|---|---|
| `PIXEL_TO_PID(PIXEL_S, pid)` | 957,560 | each AP 5-arc-min pixel → the LUMEN pid containing it |
| `PIXEL_NOPID(PIXEL_S)` | 6,778 | AP pixels whose 0.25° cell is not in the LUMEN land mask |
| `pixel_coords(PIXEL_S, coord)` | 964,338 × 2 | AP pixel centres |
| `pid_coords(pid, coord)` | 257,489 × 2 | LUMEN pid centres |

**`<cty>_crop_in_pid_coords_rescaled.gdx`** — AP's crop data on the pid grid, rescaled to LUMEN

| symbol | what |
|---|---|
| `p_Area_pid`, `p_Production_pid` `(pid,JCROP,SYS)` | AP's data summed onto the pid grid, untouched (1000 ha, 1000 t) |
| `p_Area_rescaled`, `p_Production_rescaled`, `p_Yield_rescaled` | rescaled so Σ crops = `lu_out(pid,'crop',base_year)`; yield unchanged |
| `p_Area_unanchored`, `p_Production_unanchored`, `p_Yield_unanchored` | pids with AP data but no usable LUMEN anchor — **original values, not scaled** |
| `rescale_factor(pid)`, `lu_out_crop_base(pid)`, `lumen_crop_unfilled(pid)` | the factor, its target, and LUMEN cropland on pids where AP has no crop mix |
| `pid_used`, `pid_rescaled`, `pid_unanchored`, `pid_outside_run`, `pid_luzero`, `pid_lumen_only` | pid classification (see below) |
| `n_ap_pix(pid)` | AP pixels feeding the pid; 9 = fully covered — **the first filter to reach for** |
| `PIXEL_TO_PID_AP`, `pid_coords_used`, `p_*_unmapped`, `base_year` | the map used, coords, the residual, the anchor year |

Everything else is in **`output/secondary/`**: the un-rescaled intermediate GDX
(`<cty>_crop_in_pid_coords.gdx`), CSV versions of every table, the per-pid comparison against
`lu_out`, the GAMS listing, `run_log.txt` and `audit_report.txt`.

## What the pipeline does

```
src/run.py                   driver: paths, country code, base year, stop-on-failure
  1 src/step1_crosswalk.py   Python   master grid + AP file  →  pid grid          (geometry + sums)
  2 src/step2_rescale.gms    GAMS     pid grid + lu_out      →  rescaled GDX      (the arithmetic)
  3 src/step3_report_audit.py Python  CSVs + 40 independent checks against the source files
```

**Step 1 — geometry.** Both grids are cell-centre grids on the same origin and
0.25° = 3 × (1/12°), so 9 AP pixels nest exactly in one pid. For an AP centre `X`:
`i24 = round(24·X)` (always odd), `m = floor(i24 / 6)`, pid centre `= (2m+1)/8`. `floor` toward −∞,
not truncation, or the western/southern hemispheres shift by one cell. An AP centre can never sit
on a pid boundary, so there is no tie-break. The step refuses to run if either file's coordinates
are not on its expected grid. Area and production are then plain sums over the ≤ 9 child pixels,
so they are conserved exactly; pixels whose cell is outside the LUMEN land mask go to
`p_Area_unmapped` rather than being dropped.

**Step 2 — rescale.** Per pid, yield is computed first from the untouched originals and held
fixed; area and production are then multiplied by `lu_out(pid,'crop',base_year) / Σ_j p_Area_pid`.
The within-pid crop mix is unchanged — the rescale sets each pid's *level*, never its composition.

| pid set | meaning | treatment |
|---|---|---|
| `pid_rescaled` | AP area > 0 and LUMEN crop > 0 | rescaled |
| `pid_outside_run` | AP area > 0, pid not in `pid_run` | preserved unscaled, flagged |
| `pid_luzero` | AP area > 0, in `pid_run`, LUMEN crop = 0 | preserved unscaled, flagged |
| `pid_lumen_only` | LUMEN crop > 0, AP has no crop mix | **left unfilled** — inventing a mix would be fabrication |

**Step 3 — audits.** Re-derives the crosswalk and the rescale from the *source* files and
compares against the delivered GDX: clean 1-to-1 map, every pixel inside its pid's box, per-cell
re-sums, grand totals, per-pid anchor match, factor consistency, yield invariance, AGG = IR + RF,
crop mix preserved, unanchored records bit-identical, record partition. All 40 must pass.

## Read before using the rescaled numbers

- **Base year is an assumption.** The anchor defaults to the first year in `solution_lu` (2021).
  AP's file carries no year; if its vintage is not the base year, every factor is off by the
  national growth ratio. Confirm the vintage with AP.
- **Factors are extreme on partially covered pids.** For Kenya the median factor is 2.0 but the
  95th percentile is 73 and the maximum 16,426 — a cell where AP saw a trace of cropland and LUMEN
  a full cell. Fully covered pids (`n_ap_pix = 9`) behave far better (median 1.6, max 220). Filter
  on `n_ap_pix` first.
- **Rescaled production is AP's yields on LUMEN's cropland extent**, not an independent estimate.
- **LUMEN's `crop` pool and AP's `p_Area` are not the same quantity** (land-cover pool vs sum of
  32 crop-specific areas), so AP being ~78 % of LUMEN in Kenya is a definitional gap, not a
  mapping error. The crosswalk cannot resolve it.

The full derivation, the grid proofs and the Kenya-specific numbers are in
`docs/README_coordinate_translation_2026-09_KEN.md` (the original working note).

## Provenance

Rebuilt from the September 2026 `coordinates mapping` work. On the same Kenya inputs the new
pipeline reproduces every symbol of the original deliverables: identical record counts and set
membership, values equal to floating-point noise (max absolute difference 2.6e-9 on a factor of
16,426). Symbol renames versus the original files: `PIXEL_TO_PID_KEN` → `PIXEL_TO_PID_AP`,
`lu_out_crop_2021` → `lu_out_crop_base` (+ scalar `base_year`), so downstream code does not
change with the country or the year.

## License and citation

Released under the Creative Commons Attribution 4.0 International license (see `LICENSE`). Cite as given in `CITATION.cff`: Mishra & Petsakos et al. (2026), *Land Use Model with Environmental Nexus (LUMEN) and LUMEN-Crop: Model documentation*, IFPRI.
