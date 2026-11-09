# LUMEN-Crop

Puts AP's 5-arc-minute crop downscale onto the LUMEN 0.25° `pid` grid and balances it so that, in the
base year, three things hold at once:

1. **country** — LUMEN's `lu_out` crop total equals IMPACT's `AREACTYX0` total (through IMPACT's cropping intensity);
2. **per pid** — the crop areas on every pid sum to that pid's `lu_out` crop pool (`lu_out` is the ground truth);
3. **per crop and system** — the national total of every crop-system equals IMPACT's `AREACTYX0`.

One command, four inputs, three deliverables: the crosswalk, the balanced GDX, and one hand-off GDX with
everything the Crop Allocation Model needs.

## Run it

```
run.bat --impact C:\EPTD\Modeling\f_landuse\OutputFiles\Scenarios\SSP2-MRI-370-379-LUREF.gdx
```

That is the whole pipeline (about 25 s). It stops at the first failed check and says which one.
Options are passed straight through, e.g.

```
run.bat --ap input\AP_UGA_downscale.gdx --impact <scenario.gdx>   # a different AP country file
run.bat --impact <scenario.gdx> --baseyear 2025                    # anchor to a different year
run.bat --fresh --impact <scenario.gdx>                             # wipe output\ first
run.bat --help
```

`--impact` can be omitted if the IMPACT scenario file is copied to `input\impact_scenario.gdx`.
`run.bat` uses the Python bundled with GAMS 49 (`C:\GAMS\49\GMSPython`), which already has pandas and
`gams.transfer`. Nothing else needs installing. If GAMS lives elsewhere, edit the one `GAMSDIR` line
at the top of `run.bat`.

## Inputs (`input/`)

The LUMEN solution, the Crop Allocation Model country file and the IMPACT scenario are private inputs
and are not in this repository. Only the master grid `PIXEL_TO_DIM.gdx` is tracked.

| file | owner | swap it? | what it is |
|---|---|---|---|
| `solution_lu.gdx` | LUMEN | **yes, every run** | a LUMEN solution: `pid`, `pid_coords`, `pid_run`, `pid_cty`, `cty_run`, `yrs`, `lu_out` |
| IMPACT scenario GDX (`--impact`) | IMPACT | **yes, with the LUMEN run** | the scenario LUMEN was driven by (e.g. `SSP2-MRI-370-379-LUREF.gdx`, 200+ MB). Only `AREACTYX0`, `CROPINTENSX0`, `LANDX0`, `YLDCTYX0` are read |
| `AP_KEN_downscale_for_ABHI.gdx` | AP | **yes, per country** | `PIXEL_TO_DIM` (its own pixels), `p_Area` (**physical** area: SPAM physical area mapped to IMPACT crops, 1000 ha), `p_Production` (1000 t). No harvested layer, no yield |
| `PIXEL_TO_DIM.gdx` | AP | no, fixed | master 5-arc-min grid: every pixel key → (X, Y) centre, 964,338 pixels |

The IMPACT file must be the one the LUMEN run used: LUMEN's crop control total is IMPACT's `LANDX0`,
and the pipeline refuses to run if `lu_out` and `AREACTYX0 / CROPINTENSX0` disagree by more than 1e-6.
The country code is read from `cty_run` inside the LUMEN file.

## Deliverables (`output/`)

**`pixel5min_to_pid025.gdx`** — the general crosswalk, global, independent of the AP country file

| symbol | records (KEN run) | |
|---|---|---|
| `PIXEL_TO_PID(PIXEL_S, pid)` | 957,560 | each AP 5-arc-min pixel → the LUMEN pid containing it |
| `PIXEL_NOPID(PIXEL_S)` | 6,778 | AP pixels whose 0.25° cell is not in the LUMEN land mask |
| `pixel_coords(PIXEL_S, coord)` | 964,338 × 2 | AP pixel centres |
| `pid_coords(pid, coord)` | 257,489 × 2 | LUMEN pid centres |

**`<cty>_for_CropAllocation.gdx`** — the one file to hand to the Crop Allocation Model (step 5). LUMEN pixel
`KEY` as the spatial unit (the Crop Allocation Model's own name for the selected layer); `p_Area` / `p_Area_harv` harvested, `p_Area_phys` physical, `p_Production`,
`p_Yield` (+ `p_YieldSource`, `p_SeedSource`), `p_Cropland(KEY,yrs)` = LUMEN cropland path for every year,
`p_Land(KEY,fland,yrs)`, `AREACTYX0`, `YLDCTYX0`, `CROPINTENSX0`, `LANDX0` for every year, the AP originals
on the pid grid, the crosswalk `PIXEL_TO_PID` for the AP pixels of the country file, and `p_Coords`.
Every symbol's explanatory text states its unit and whether it is harvested or physical area.

**`<cty>_crop_in_pid_coords_balanced.gdx`** — AP's crop data on the pid grid, balanced to LUMEN and IMPACT

| symbol | what |
|---|---|
| `p_Area_lu(pid,JCROP,SYS)` | **physical cropland by crop and system** (1000 ha). Per pid, Σ over crops and IR+RF = `lu_out(pid,'crop',base_year)` |
| `p_Area_harv(pid,JCROP,SYS)` | **harvested area** = `p_Area_lu` × cropping intensity (1000 ha). Per crop-system, Σ over pids = `AREACTYX0` |
| `p_Production_harv`, `p_Yield_used`, `yield_source` | production (1000 t) = physical area × AP yield per physical ha, or harvested area × IMPACT yield; `p_Yield_used` = production / harvested area; where the yield came from (1 AP cell, 2 AP country, 3 IMPACT) |
| `seed`, `seed_source`, `ras_row(pid)`, `ras_col(cty,JCROP,SYS)` | the RAS seed, where each seed cell came from (1 AP cell, 2 column fallback, 3 row fallback) and the two multipliers: `p_Area_lu = seed × ras_row × ras_col` |
| `lu_out_crop_base(pid)`, `target_harv`, `target_lu`, `ci(cty)`, `col_scale(cty)` | the row targets, the column targets (harvested and physical), the cropping intensity, and the LUMEN/IMPACT total ratio (1 to 1e-12) |
| `cty_lu_crop`, `cty_harv`, `cty_phys`, `cty_landx0`, `cty_gap_rel` | check 1 per country |
| `pid_balanced`, `pid_seed_ap`, `pid_seed_nat`, `pid_outside_run`, `pid_luzero` | pid classification (see below) |
| `js_balanced`, `js_seed_ap`, `js_seed_sys`, `js_no_target` | crop-system classification |
| `p_Area_ap_dropped`, `p_Production_ap_dropped` | AP records that could not be used, with the originals |
| `p_Area_pid`, `p_Production_pid` | AP's data summed onto the pid grid, untouched (1000 ha **physical**, 1000 t) |
| `n_ap_pix(pid)` | AP pixels feeding the pid; 9 = fully covered — **the first filter to reach for** |
| `PIXEL_TO_PID_AP`, `pid_coords_used`, `p_*_unmapped`, `base_year`, `n_iter` | the map used, coords, the residual, the anchor year, RAS iterations |

Everything else is in **`output/secondary/`**: the intermediate GDX files (`<cty>_crop_in_pid_coords.gdx`,
`<cty>_impact_targets.gdx`, `<cty>_totals.gdx` from step 4), the CSVs (`<cty>_crop_by_pid_<yr>.csv`, `<cty>_crop_by_country_<yr>.csv`,
`<cty>_pid_summary_<yr>.csv`, `<cty>_ap_dropped_<yr>.csv`, `<cty>_crop_compare_by_pid_<yr>.csv`), the GAMS
listings (`step2_balance.lst`, `step4_totals.lst`), `run_log.txt` and `audit_report.txt`. **`<cty>_crop_by_country_<yr>.csv` is the table to look at
first**: one row per crop-system with AP's original, IMPACT's target, the balanced result and the RAS column factor.

## What the pipeline does

```
src/run.py                    driver: paths, country code, base year, stop-on-failure
  1 src/step1_crosswalk.py    Python   master grid + AP file  →  pid grid           (geometry + sums)
    src/impact_targets.py     Python   IMPACT scenario        →  country targets    (step 1b, check 1 by year)
  2 src/step2_balance.gms     GAMS     pid grid + lu_out + targets  →  balanced GDX (RAS)
  3 src/step3_report_audit.py Python   CSVs + 57 independent checks against the source files
  4 src/step4_totals.gms      GAMS     country crop totals, yields and land totals by pool at every stage -> totals GDX
  5 src/step5_handoff.gms     GAMS     one GDX for the Crop Allocation Model: <cty>_for_CropAllocation.gdx
```

**Step 1 — geometry.** Both grids are cell-centre grids on the same origin and
0.25° = 3 × (1/12°), so 9 AP pixels (3 × 3) nest exactly in one pid. For an AP centre `X`:
`i24 = round(24·X)` (always odd), `m = floor(i24 / 6)`, pid centre `= (2m+1)/8`. `floor` toward −∞,
not truncation, or the western/southern hemispheres shift by one cell. An AP centre can never sit
on a pid boundary, so there is no tie-break. The step refuses to run if either file's coordinates
are not on its expected grid. Area and production are then plain sums over the ≤ 9 child pixels,
so they are conserved exactly; pixels whose cell is outside the LUMEN land mask go to
`p_Area_unmapped` rather than being dropped.

**Step 1b — IMPACT targets.** Reads `AREACTYX0(j,cty,fctr,yrs)` (harvested area; `air`→`IR`,
`arf`→`RF`, `AGG` = sum), `CROPINTENSX0`, `LANDX0` and `YLDCTYX0` for the countries in `cty_run`, and
checks the identity that ties LUMEN to IMPACT in every LUMEN year:

```
Σ_pid lu_out(pid,'crop',yr)  =  LANDX0(cty,'crop',yr)  =  Σ_j AREACTYX0(j,cty,·,yr) / CROPINTENSX0(cty,yr)
```

LUMEN's `crop` pool and AP's `p_Area` are *physical* cropland (AP's export writes SPAM's physical area,
`p_MapPhysP`, mapped to IMPACT crops); IMPACT's `AREACTYX0` is *harvested* area. LUMEN and IMPACT differ
by the cropping intensity (0.8025 for Kenya). AP's total, 5,777 kha, is 78 % of LUMEN's 7,396 kha because
SPAM's physical cropland for Kenya is smaller than IMPACT's `LANDX0`, not because of a basis difference
or a mapping error. The balance only uses AP's spatial pattern, so this gap is absorbed by the RAS factors.

**Step 2 — balance (RAS).** Picture a table with one row per LUMEN pixel and one column per crop and
system, each cell holding hectares. AP filled the cells. Two other sources dictate what the margins of
that table must add up to: LUMEN gives every **row total**, the physical cropland `lu_out(pid,'crop',base_year)`
of each pixel; IMPACT gives every **column total**, the harvested area `AREACTYX0(j,cty,s,base_year)`
of each crop-system, converted to physical hectares by dividing by `CROPINTENSX0`. Check 1 guarantees
that both sets of totals add up to the same national number (the residual ratio is kept in `col_scale`).
AP's cells match neither set of totals, so they have to move.

RAS moves them the way one would by hand. Pass 1 goes through the rows: if a pixel should hold 100 kha
and its cells add up to 80, every cell in that row is multiplied by 1.25; afterwards every pixel total is
right. Pass 2 goes through the columns: if rainfed maize should total 2,632 kha nationally and now totals
2,900, every cell in that column is multiplied by 0.91; afterwards every crop total is right, but the rows
are slightly off again. The passes alternate, each correction smaller than the last, until both margins
are within 1e-10 of their targets (42 passes for Kenya), and one final row pass makes every pixel total
equal `lu_out` exactly, because LUMEN has the last word. Every multiplier a row ever received is
accumulated into `ras_row(pid)`, every multiplier a column received into `ras_col(cty,j,s)`, so for each
cell AP supplied:

```
p_Area_lu(pid,j,s)  =  p_Area_pid(pid,j,s)  ×  ras_row(pid)  ×  ras_col(cty,j,s)
```

Three properties follow. (i) Ratios inside a row and inside a column are preserved: if AP put twice as
much maize as beans on a pixel, or three times the tea on pixel A as on pixel B, that is still true
afterwards; only the levels change. (ii) Zeros stay zeros, so no crop appears where AP had none.
(iii) Among all tables with the required margins this is the closest to AP's, in the minimum
cross-entropy sense; it is the least disruptive adjustment, not merely a convenient one. The one thing
RAS cannot do is fill a cell that is empty but must carry area, so where AP has nothing the seed is
filled in first and flagged:

| `seed_source` | where | seed | KEN 2021 |
|---|---|---|---|
| 1 | AP has the cell | AP's `p_Area_pid` | 607 pids, 41 crop-systems, 5,704 kha |
| 2 | crop-system with IMPACT area but no AP area anywhere in the country | the column target spread like AP's total area in that system (the IR footprint for IR) | 25 crop-systems, 36 kha harvested (0.6 % of `AREACTYX0`) |
| 3 | pid with LUMEN cropland but no usable AP crop mix | the pid's cropland split by the national IMPACT mix | 155 pids, 263 kha physical (3.6 % of `lu_out` crop) |

AP area that cannot be used is dropped and reported in `p_Area_ap_dropped` and the dropped CSV:

| pid / column set | meaning | KEN 2021 |
|---|---|---|
| `pid_outside_run` | AP area on a pid LUMEN assigns to another country (`pid_cty`) | 35 pids, 73.0 kha |
| `pid_luzero` | AP area on a `pid_run` pid whose `lu_out` crop is 0 | none |
| `js_no_target` | crop-system AP reports but IMPACT has no area for | `jtols/RF`, 0.06 kha |

AP's file has no yield, and AP production over AP area is a yield per *physical* hectare because AP's
area is physical. Production therefore follows physical area: `p_Area_lu` × (AP production / AP area)
where AP has the cell (`yield_source` 1) or AP's national value for the crop-system (2); where neither
exists IMPACT's `YLDCTYX0`, per harvested hectare, is applied to `p_Area_harv` (3). `p_Yield_used` is
reported on one basis, t per harvested ha = production / `p_Area_harv`, so AP-based yields appear
divided by the cropping intensity.

**Step 3 — audits.** Re-derives everything from the *source* files (AP file, `solution_lu`, the IMPACT
scenario) and compares against the delivered GDX: clean 1-to-1 map, every pixel inside its pid's box,
per-cell re-sums, grand totals, check 1 against `AREACTYX0 / CROPINTENSX0` and `LANDX0`, the per-pid
margin on all 762 pids, the per-crop-system margin on all 66 columns, harvested = physical × CI,
AGG = IR + RF, `p_Area_lu = seed × ras_row × ras_col` on every seeded cell and zero elsewhere, seed
provenance, yield provenance (on both area bases), dropped-area accounting. All 57 must pass.

**Step 4 — totals and yields.** `src/step4_totals.gms` reads the AP file, `solution_lu`, the step 1 and
1b GDX files and the balanced GDX, and displays (nothing is written) `crop_tot(stage,cty,SYS,metric)`:
area (1000 ha), production (1000 t) and aggregate yield (t/ha) for the AP source file, AP on the pid grid,
the unmapped residual, the IMPACT targets (harvested, physical, `LANDX0`), `lu_out` crop, the balanced
result and the dropped AP area. Rows are the `cty_run` countries plus `other_cty` (AP area on pids LUMEN
assigns to a neighbour, all of it dropped in step 2) and `ALL`. AP's file carries no yield and its area is
physical, so AP production over area is a yield per physical hectare; wherever it is set beside IMPACT's
`YLDCTYX0` or the balanced `p_Yield_used` (both per harvested hectare) it is divided by the cropping
intensity first. `crop_cmp(cty,JCROP,SYS,item)` is the crop-specific table: one row per crop and system
plus `ALL_CROPS`, with AP physical area beside the balanced physical area and their ratio (what the balance
did to AP), IMPACT harvested area beside the balanced harvested area, the dropped AP area, AP, IMPACT and
balanced production, AP yield per physical and per harvested-equivalent hectare, IMPACT and balanced yield,
and the yield ratios balanced/AP and balanced/IMPACT. `yld_summary` gives the area-weighted mean absolute deviation of the balanced yields
from each source. `pid_check(pid,·)` lists, for every pid in `pid_run`, `lu_out` crop, the balanced physical
area, their difference and relative difference; `cs_check(cty,JCROP,SYS,·)` does the same per crop-system against
`AREACTYX0`; `margin_check` holds the worst case of each and the number of rows or columns off by more than 1e-9
(EPS means none). `land_tot(cty,pool,source)` shows `lu_out` summed over
`pid_run`, `lu_cty` and the IMPACT control at the base year, and `land_by_year` the `lu_out` pools by year.
The tables are echoed to the console, kept in `output/secondary/step4_totals.lst` and unloaded unchanged to
`output/secondary/<cty>_totals.gdx`; to rerun on its own:
`C:\GAMS\49\gams.exe src\step4_totals.gms pf=output\secondary\step4_totals.pf`.

**Step 5 — hand-off to the Crop Allocation Model.** `src/step5_handoff.gms` writes the third deliverable,
`output/<cty>_for_CropAllocation.gdx`: everything the Crop Allocation Model needs from this pipeline in one
file, with the LUMEN 0.25° pixel as the spatial unit (set `KEY`, the model's own name for its layer elements;
GAMS is case-insensitive, so it cannot be called `PID` beside LUMEN's `pid`) and names that follow that model
where a counterpart exists. Every explanatory text states unit and basis. Harvested area: `p_Area` (= `p_Area_harv`),
`AREACTYX0`. Physical area: the AP file and `p_Area_AP`, `p_Area_phys`, `p_Cropland(KEY,yrs)` (= `lu_out` crop, the land
constraint path for every year), `p_Land(KEY,fland,yrs)`, `LANDX0`. `p_Production`, `p_Yield`,
`p_YieldSource` and `p_SeedSource` carry production, the yield applied and where each cell came from;
`p_RasRow`/`p_RasCol` the two balancing factors; `p_Area_AP`, `p_Production_AP` and `p_Area_AP_dropped` the
AP originals on the pid grid and what was dropped; `PIXEL_TO_PID` the crosswalk for the AP pixels of the
country file, `PIXEL_NO_PID` and `PID_NOT_CTY` the two kinds of edge cases; `YLDCTYX0`, `CROPINTENSX0`
and `p_Coords` complete it. The script refuses to write the file unless the pixel sums of `p_Area_phys`
reproduce `p_Cropland` and the crop-system sums of `p_Area` reproduce `AREACTYX0` at the base year. The same two
identities are also in the file as tables, so they can be checked without this pipeline: `Test_PixelSum(KEY,·)`
(one row per pixel: `LUMEN_phys` = `p_Cropland`, `BAL_phys_sum` = sum of `p_Area_phys` over crops, the derived
harvested sum, AP's original physical sum and the balanced/AP ratio for reference, `diff` = balanced minus LUMEN, `rel_diff` = `diff` / LUMEN), `Test_CropSum(cty,JCROP,SYS,·)` (one
row per crop-system: `IMPACT_harv` = `AREACTYX0`, `BAL_harv_sum` = sum of `p_Area` over pixels, the derived physical
sums and AP's physical sum for reference, `diff` = balanced minus IMPACT, `rel_diff` = `diff` / IMPACT) and
`Test_Summary` with the worst case of each. Column names carry the source and the basis: LUMEN outputs physical
area only, IMPACT reports harvested area, and every harvested figure derived in the file is physical × IMPACT's
`CROPINTENSX0`.

## Kenya, base year 2021 — what the balance did

| | |
|---|---|
| check 1 | LUMEN 7,396.101 kha = 5,935.181 / 0.802474 = `LANDX0` 7,396.101 kha (relative gap 7e-16; same in all 30 years) |
| per pid | 762 pids, max relative gap 6e-16 |
| per crop-system | 66 columns, max relative gap 5e-11 (8e-9 kha) |
| RAS | 42 iterations |
| RAS column factor | between 0.7 and 1.5 for most crops; `jrice/RF` 0.04, `jsubf/RF` 0.23 at the low end; `jsugc/IR` 15.5, `jtont/RF` 69, `jothr/RF` 75 at the high end |
| RAS row factor (AP-seeded pids) | area-weighted mean 1.25 (= 1/CI), median 5.4, p95 657, max 73,355; fully covered pids (9/9, 384 pids) median 2.5, max 1,213 |
| production | see `run_log.txt`: balanced vs 25,205 kt in AP (AP yields per physical ha on LUMEN's physical area; IMPACT yields on fallback cells) |

## Read before using the numbers

- **Base year is an assumption.** The anchor defaults to the first year in `solution_lu` (2021).
  AP's file carries no year; if its vintage is not the base year, every factor is off by the
  national growth ratio. Confirm the vintage with AP.
- **Two area concepts, both delivered.** Use `p_Area_lu` when the question is land (it adds up to
  LUMEN's pools) and `p_Area_harv` when it is crop statistics (it adds up to IMPACT). They differ by
  one national factor, IMPACT's cropping intensity.
- **Where AP and IMPACT disagree, the balance sides with IMPACT nationally and keeps AP's pattern.**
  `jtont` (0.07 kha in AP, 175 kha in IMPACT) and `jothr` (0.08 vs 44 kha) are placed by inflating a
  trace signal in AP about 70-fold, so their spatial pattern carries little information. `jtemf` and
  `jrpsd` are absent from AP's crop list though IMPACT has 19 and 12 kha; `jtols` is in AP but not in
  IMPACT. These are questions for AP, not for the crosswalk. The column factors in
  `<cty>_crop_by_country_<yr>.csv` show every such case.
- **Fallback seeds are assumptions, flagged, not data.** 3.6 % of LUMEN's cropland sits on pids where
  AP reports nothing and carries the national crop mix; filter on `seed_source` or `pid_seed_nat` to
  exclude it.
- **Row factors are extreme on partially covered pids**, exactly as before: a cell where AP saw a
  trace of cropland and LUMEN a full cell. Fully covered pids (`n_ap_pix = 9`) behave far better.
  Filter on `n_ap_pix` first.
- **Production is AP's yields applied to LUMEN's physical area**, not an independent estimate. AP's
  area is physical, so AP production / AP area is a yield per physical hectare and production scales
  with `p_Area_lu`; on fallback cells the yield is AP's national or IMPACT's (`yield_source`). The
  reported `p_Yield_used` is per harvested hectare, so AP-based values appear divided by the cropping
  intensity. A SPAM harvested layer would make the yields exact; AP's export does not include one.
- **35 pids with 73 kha of AP Kenyan crop area lie on pixels LUMEN assigns to neighbouring
  countries.** They are not part of Kenya's balance; the dropped CSV lists them with LUMEN's country.

The grid derivation and the September Kenya diagnostics are in
`docs/README_coordinate_translation_2026-09_KEN.md`; its rescale section is superseded by this README.

## Provenance

Version 1 (2 November 2026) rebuilt the September 2026 `coordinates mapping` work as a pipeline and
reproduced its per-pid rescale symbol for symbol. Version 2 (9 November 2026) replaces that rescale,
which matched `lu_out` per pid but left national crop totals wherever AP had them, with the RAS
balance described here, adds the IMPACT scenario as an input, and renames the deliverable to
`<cty>_crop_in_pid_coords_balanced.gdx`. The crosswalk deliverable and step 1 are unchanged.

## License and citation

Released under the Creative Commons Attribution 4.0 International license (see `LICENSE`). Cite as given in `CITATION.cff`: Mishra & Petsakos et al. (2026), *Land Use Model with Environmental Nexus (LUMEN) and LUMEN-Crop: Model documentation*, IFPRI.
