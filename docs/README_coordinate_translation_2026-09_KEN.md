> **Status (November 2026).** This is the September 2026 working note, kept for the grid derivation and
> the Kenya diagnostics. Its second part, *Rescaling AP's crop data onto LUMEN's cropland totals*, describes a
> per-pid rescale that the pipeline no longer produces: it has been replaced by the RAS balance in
> `src/step2_balance.gms`, which matches `lu_out` per pid **and** IMPACT's `AREACTYX0` per crop and system.
> The "AP is 78 % of LUMEN" gap discussed below is real and has no basis explanation: AP's `p_Area` is SPAM's
> *physical* area mapped to IMPACT crops (confirmed from AP's export code), so both sides are physical and SPAM
> simply carries less cropland for Kenya than IMPACT's `LANDX0`. The RAS balance absorbs the gap; see the
> top-level README. Symbol names in that part (`p_Area_rescaled`, `rescale_factor`, ...) no longer exist.

# Translating AP's 5-arcmin `PIXEL_TO_DIM` grid into the LUMEN 0.25° `pid` grid

## Who owns what

| file | owner | what it is |
|---|---|---|
| `PIXEL_TO_DIM.gdx` | **AP** | 5-arcmin pixel keys → lon/lat |
| `AP_KEN_downscale.gdx` | **AP** | Kenya downscaled crop area & production, per 5-arcmin pixel |
| `solution_lu_KEN.gdx` | **LUMEN** | 0.25° `pid` grid, `pid_coords`, `lu_out` land-use pools |

## The two grids

| | AP (`PIXEL_TO_DIM.gdx`) | LUMEN (`solution_lu_KEN.gdx`) |
|---|---|---|
| resolution | 5 arc-min = 1/12° | 15 arc-min = 0.25° |
| key | `PIXEL_S` (e.g. `4430572`) | `pid` (e.g. `p200515`) |
| coords stored as | two set labels: X, Y | `pid_coords(pid,coord)`, `coord = x,y` |
| convention | cell **centre** | cell **centre** |
| extent | 964,338 pixels | 257,489 pixels |

Both are cell-centre grids on the **same origin**, and 0.25° = 3 × (1/12°), so the grids
nest exactly: **9 AP pixels per one LUMEN pid**, 3 × 3.

Verified numerically:
- every AP X and Y satisfies `coord × 24` = an **odd** integer → centres at `(2k+1)/24`
- every LUMEN X and Y satisfies `coord × 8` = an **odd** integer → centres at `(2m+1)/8`

Because `(2k+1)` is always odd and a 0.25° cell boundary sits at a multiple of `6/24`,
an AP cell centre can **never** land on a LUMEN cell boundary. The assignment is therefore
unambiguous — no tie-breaking rule is needed.

AP's key decodes exactly as the standard global 5-arc-min raster (4320 × 2160), i.e. the
SPAM grid — `row = PIXEL_S // 4320`, `col = PIXEL_S % 4320`,
`lon = -180 + (col+0.5)/12`, `lat = 90 - (row+0.5)/12`, matching the stored coordinates to
3.3e-4° (label rounding only). LUMEN's `pid` is *not* a global raster index: it is a
sequential land-only ID, row-major from the NW, covering 257,489 of the 1,036,800 global
quarter-degree cells (24.8%).

In kilometres, 5 arc-min ≈ 9.27 km and 0.25° ≈ 27.80 km at the equator (the "10 km" and
"25 km" shorthands). Do not do the arithmetic in km — 25/10 = 2.5 would not nest. In
degrees the ratio is exactly 3.

## The mapping

For an AP pixel at centre `(X, Y)`:

```
i24 = round(X * 24)            // odd integer, units of 1/24 deg
m   = floor(i24 / 6)           // index of the containing 0.25-deg cell (floor toward -inf)
X_pid = (2*m + 1) / 8          // = m*0.25 + 0.125, the centre of the LUMEN cell
```

Same for `Y`. Then look up `pid` by `(X_pid, Y_pid)` in `pid_coords`.
Use `floor` toward −∞ (Python `//`, GAMS `floor`), **not** truncation — otherwise
western/southern hemisphere cells shift by one.

## Files produced

**GDX**
- `pixel5min_to_pid025.gdx` — the general crosswalk
  - `PIXEL_TO_PID(PIXEL_S, pid)` — 957,560 pairs, global
  - `pid_coords(pid, coord)` — LUMEN cell-centre coords, 130,187 pids
- `KEN_crop_in_pid_coords.gdx` — **AP's Kenya downscale expressed on the LUMEN grid**
  - `p_Area_pid(pid, JCROP, SYS)` — 17,994 records (1000 ha)
  - `p_Production_pid(pid, JCROP, SYS)` — 17,994 records (1000 t)
  - `pid_coords_used(pid, coord)`, `pid_used(pid)` — 642 LUMEN pids
  - `n_ap_pix(pid)` — how many AP pixels fed each pid (9 = fully covered)
  - `PIXEL_TO_PID_KEN(PIXEL_S, pid)` — 4,646 of AP's 4,668 KEN pixels
  - `p_Area_unmapped`, `p_Production_unmapped` — the residual, see below

**CSV (same content, for inspection)**
- `crosswalk_pixel5min_to_pid025.csv` — `pixel_s, pixel_x, pixel_y, cell_x, cell_y, pid`
- `crosswalk_KEN_pixels.csv`, `KEN_p_Area_by_pid.csv`, `KEN_p_Production_by_pid.csv`
- `KEN_crop_compare_by_pid_2021.csv` — AP crop area vs LUMEN `lu_out` pools, per pid
  (`n_ap_pixels`, `ap_crop_area_kha`, `lumen_lu_out_2021_<pool>`, `diff_crop_kha = LUMEN − AP`)

**Code**
- `build_pid_translation.gms` — rebuilds both GDX files
- `out/audit_conservation.py` — the 15-check conservation audit below
- `out/verify_resolution.py` — the grid/resolution proofs above

## Conservation check — audited per pid, not just in total

Aggregation is a plain sum over the ≤9 child pixels, so area and production are conserved.
`out/audit_conservation.py` re-derives the result from `AP_KEN_downscale.gdx`
alone (using AP's own embedded `PIXEL_TO_DIM`, not the master file the crosswalk was built
from) and compares against the delivered GDX. **15/15 checks pass:**

*The map is a clean function* — every mapped pixel has exactly one pid (no pixel split
across two pids, none double-counted); no duplicate pairs; source pixel keys and
coordinates are unique.

*Every source pixel is accounted for exactly once* — mapped (4,646) and unmapped (22) are
disjoint and together cover all 4,668; no pixel carrying data is missing from both.

*Geometric containment* — every AP pixel centre lies strictly inside its pid's 0.25° box:
max |dx| = 0.08330, max |dy| = 0.08333, against a half-width of 0.125. That maximum is
exactly 1/12°, as expected for the outer ring of a 3×3 block. No pid has more than 9
children.

*Per-pid conservation* — each of the 17,994 `(pid, crop, sys)` cells equals an independent
re-sum of its children: max abs diff **5.0e-14** (area), **5.0e-13** (production). All 642
pid totals equal the sum of their own children (max **1.1e-13**).

*Grand totals close exactly*, mapped + residual = original:

```
area  SYS=AGG  5,777.1170 kha      production  SYS=AGG  25,205.7809 kt
area  SYS=IR     107.7954 kha      production  SYS=IR    3,555.4933 kt
area  SYS=RF   5,669.3216 kha      production  SYS=RF   21,650.2876 kt
```

**Residual: 22 of AP's 4,668 KEN pixels have no `pid`.** They map to a valid 0.25° cell,
but that cell is not in the LUMEN land mask, so there is nowhere to put them. They carry
0.428 kha of 5,777.117 (0.0074%) and 0.509 kt of 25,205.781 (0.0020%). They are preserved
in `p_Area_unmapped` / `p_Production_unmapped` rather than dropped, so nothing disappears
silently. Some sit on the Kenya/South Sudan/Uganda border row (Y ≈ 4.54); the rest are
scattered near Y ≈ −0.54, −0.04, 4.29, 4.375.

## Partial coverage at the edges — affects comparison, not conservation

AP's Kenya file contains only Kenyan pixels, so pids straddling the border or coast
receive fewer than 9 children. **258 of 642 pids (40%) are partially covered**, carrying
675 kha (11.7% of AP's total):

| AP pixels per pid | pids | kha | % of AP area |
|---|---|---|---|
| 9 (full) | 384 | 5,101.6 | 88.3 |
| 5–8 | 134 | 535.4 | 9.3 |
| 1–4 | 124 | 139.7 | 2.4 |

Totals are unaffected — conservation is exact either way. But **per-pid comparison against
`lu_out` is not like-for-like on those cells**: a pid with 3 children has AP data for 1/3
of its area while `lu_out` covers the whole cell, so it looks like an AP shortfall that is
really a coverage artefact. Use `n_ap_pix(pid)` (or the `n_ap_pixels` CSV column) to
filter to fully covered pids.

Note though that restricting to the 289 fully covered pids where both are positive
*lowers* the correlation slightly, 0.66 → 0.61. Edge coverage is therefore not what drives
the disagreement between the two datasets — see below.

## Which year? — read this before comparing

**LUMEN: 2021.** The comparison uses `lu_out(pid,'crop','2021')`. 2021 is LUMEN's base
year (`impact_base` = "IMPACT 2021 totals", `luh2_base`, `bii_base` "baseline year 2021").
`lu_out` runs 2021–2050 and Kenya cropland grows steadily over that span.

**AP: unknown — the file carries no year.** `p_Area(*, JCROP, SYS)` and
`p_Production(*, JCROP, SYS)` are 3-dimensional: pixel × crop × system. There is **no year
dimension**, no year-like UEL, no set text, and no explanatory text anywhere in
`AP_KEN_downscale.gdx`. The GDX audit stamp (15 Jun 2026, GAMS 54.1.0) is the
file's creation date, not the data vintage.

So the year alignment is **an assumption, not something the data confirms.** 2021 is the
defensible default — it is LUMEN's base year, and a static downscale is most likely a base
year — but AP should confirm the vintage. It matters:

| LUMEN year | LUMEN crop (kha) | ratio LUMEN/AP |
|---|---|---|
| 2021 | 7,250 | 1.26× |
| 2030 | 8,111 | 1.40× |
| 2040 | 8,890 | 1.54× |
| 2050 | 9,753 | 1.69× |

AP's total is fixed at 5,777 kha regardless, since it has no time dimension.

## Comparing AP's crop areas against LUMEN `lu_out` — read this before drawing conclusions

The crosswalk is exact geometry. The remaining differences between AP's crop area and the
LUMEN `crop` pool are **definitional and data-lineage differences, not mapping error**,
and the crosswalk cannot resolve them:

- **The two quantities are not the same thing.** LUMEN `crop` is a *land-cover pool* —
  cropland from LUH2 baseline shares scaled to IMPACT control totals, which includes
  fallow and land not planted in a given year. AP's `p_Area` is the *sum of 32
  crop-specific areas* (IMPACT `j`-codes). Crop-specific area summed over a finite crop
  list is normally smaller than total cropland, which is the direction observed here:
  5,777 kha (AP) vs 7,250 kha (LUMEN 2021), i.e. AP is 78% of LUMEN.
- **Multi-cropping works the other way.** If AP's `p_Area` were *harvested* area,
  double-cropped cells would push it *above* physical cropland — so multi-cropping does
  not explain a shortfall, it deepens it. `p_Area` has since been confirmed to be *physical*
  area (AP's export writes `p_MapPhysP`), so this is settled: not a candidate explanation.
- **LUMEN itself undershoots its own target.** `lu_cty` KEN crop 2021 = 7,255 kha against
  an IMPACT control total of 7,396 kha; the 141 kha difference is model slack
  (`slack_check`). Compare against `lu_out`, as done here, not against `impact_base`.
- **Different pixel masks.** 35 pids carrying 73 kha of AP crop area fall outside
  `pid_run` (the 762 pixels LUMEN solves for Kenya), so they have no `lu_out` value at
  all. Conversely 63 pids carrying 187 kha of LUMEN `crop` have zero AP area.
- **Per-pid agreement is moderate.** Across the 433 pids where both are positive, the
  correlation is 0.66 (0.61 on fully covered pids). Spatial patterns broadly agree;
  individual cells often do not.

If the aim is a like-for-like comparison, settle the year and the crop-coverage question
first (does AP's 32-crop list span all cropland, and is fallow in or out?), or rescale
AP's areas to the LUMEN control totals. That is a data decision, not a coordinate one.

---

# Rescaling AP's crop data onto LUMEN's cropland totals

Everything above is exact geometry. This section is different in kind: it **adjusts AP's
numbers** so that each pid's crop area reproduces LUMEN's, at the cost of overwriting AP's
own area levels. Read the caveats before using it.

## What it does

For each pid `p`, over the 32 IMPACT crops `j` and systems `s ∈ {AGG, IR, RF}`:

```
p_Yield_rescaled(p,j,s)      = p_Production_pid(p,j,s) / p_Area_pid(p,j,s)        [t/ha]
rescale_factor(p)            = lu_out(p,'crop','2021') / Σ_j p_Area_pid(p,j,'AGG')
p_Area_rescaled(p,j,s)       = p_Area_pid(p,j,s) * rescale_factor(p)              [1000 ha]
p_Production_rescaled(p,j,s) = p_Area_rescaled(p,j,s) * p_Yield_rescaled(p,j,s)   [1000 t]
```

Yield is computed first from the untouched originals and then held fixed, so production
moves by the same factor as area and the **within-pid crop mix is unchanged** — the rescale
sets each pid's *level*, never its composition. `p_Yield_rescaled` is therefore identical to
AP's implied yield; it is carried as an explicit output so it can be inspected and sanity-
checked, not because the rescale alters it.

All 17,994 `(pid, crop, sys)` records have strictly positive area and production, so yield is
well defined everywhere — there is no division-by-zero case to handle.

## Pid classification

| set | pids | AP area (kha) | treatment |
|---|---|---|---|
| `pid_rescaled` | 433 | 5,694.5 | rescaled to `lu_out` crop 2021 (→ 7,062.9 kha) |
| `pid_unanchored` | 209 | 82.2 | **preserved unscaled**, flagged |
| ↳ `pid_outside_run` | 35 | 73.0 | outside LUMEN `pid_run` — no `lu_out` exists |
| ↳ `pid_luzero` | 174 | 9.2 | inside `pid_run` but `lu_out` crop 2021 = 0 |
| `pid_lumen_only` | 63 | — | LUMEN has 187.5 kha of crop, AP has no crop mix — **left unfilled** |

`pid_rescaled` and `pid_unanchored` partition `pid_used` exactly (433 + 209 = 642), and their
records partition the original 17,994 (14,811 + 3,183). Unanchored values are bit-identical
to `p_Area_pid` / `p_Production_pid` — not a rounded copy.

Nothing is synthesised. The 187.5 kha of LUMEN cropland on pids where AP has no crop
composition is **reported, not filled**: inventing a crop mix there would be fabrication, so
it is left to the user to decide. Consequently the delivered total (7,145.0 kha) does not
equal LUMEN's Kenya total (7,250.3 kha); the 105.3 kha difference is 187.5 unfilled minus the
82.2 preserved.

## ⚠ The factor distribution — the main caveat

Matching per-pid means accepting whatever factor that requires, and the factors are extreme:

| | min | p05 | median | p95 | max |
|---|---|---|---|---|---|
| all 433 rescaled pids | 0.046 | 0.29 | **2.05** | 73.1 | **16,426** |
| fully covered (9/9) — 289 pids | | | 1.59 | | 219.8 |
| partially covered (<9) — 144 pids | | | 6.81 | | 16,426.5 |

A factor of 16,426 means AP observed a trace of cropland in that cell and LUMEN reports a
full cell of it; the rescale then inflates AP's crop mix by four orders of magnitude. The
resulting areas are arithmetically correct but carry essentially **no information from AP
beyond the crop mix**. Partially covered pids are far worse than fully covered ones, so
`n_ap_pix(pid)` remains the first filter to reach for.

**Implication for production and yield.** Production is scaled by the same factor, so
national rescaled production is 27,041 kt against AP's original 25,205 kt. That number
inherits every distortion above. Yields are unchanged and remain AP's, so the rescaled
production is best read as "AP's yields applied to LUMEN's cropland extent", not as an
independent production estimate.

**The 2021 assumption is unchanged and still unconfirmed** (see the year section above). The
anchor is `lu_out(pid,'crop','2021')`. If AP's vintage is not 2021, every factor is wrong by
the corresponding national growth ratio.

## Files produced

**GDX** — `KEN_crop_in_pid_coords_rescaled.gdx`, a superset of `KEN_crop_in_pid_coords.gdx`
- `p_Area_rescaled`, `p_Production_rescaled`, `p_Yield_rescaled` — 14,811 / 14,811 / 17,994
- `p_Area_unanchored`, `p_Production_unanchored`, `p_Yield_unanchored` — 3,183 each
- `rescale_factor(pid)`, `lu_out_crop_2021(pid)`, `lumen_crop_unfilled(pid)`
- `pid_rescaled`, `pid_unanchored`, `pid_outside_run`, `pid_luzero`, `pid_lumen_only`
- the originals `p_Area_pid`, `p_Production_pid`, `pid_coords_used`, `n_ap_pix`, and the
  unmapped-pixel residuals, all carried through unchanged

**CSV**
- `KEN_crop_rescaled_by_pid_2021.csv` — 14,811 rows: `pid, jcrop, sys, area_rescaled_kha,
  prod_rescaled_kt, yield_t_per_ha`
- `KEN_crop_unanchored_by_pid_2021.csv` — 3,183 rows, with a `reason` column
- `KEN_crop_rescale_factors_by_pid_2021.csv` — 705 rows, one per pid, with coords,
  `n_ap_pixels`, `factor` and `status`

**Code**
- `build_rescale.gms` — does all the arithmetic, reading `solution_lu_KEN.gdx` and
  `KEN_crop_in_pid_coords.gdx` directly. No CSV staging in the numeric path, so nothing is
  lost to text round-tripping and the build is reproducible from the two source GDX files.
- `out/rescale_report.py` — reads the GDX and writes the CSVs; recomputes nothing
- `out/audit_rescale.py` — the 22-check audit below

## Verification

`build_rescale.gms` carries four in-build `abort` guards (per-pid match within 1e-9 relative,
positive factors, pid partition, record partition). `out/audit_rescale.py` then re-derives the
rescale independently — from the originals inside the delivered GDX and from `lu_out` read
straight out of `solution_lu_KEN.gdx`, not from anything the build wrote. **22/22 checks pass:**

- **the headline:** for all 433 rescaled pids, `Σ_j p_Area_rescaled(p,j,'AGG')` equals
  `lu_out(p,'crop','2021')` — max relative error **4.8e-15**, max absolute **1.4e-13 kha**
- the delivered anchor equals the LUMEN source file exactly (max diff **0.0**)
- `rescale_factor` = anchor ÷ AP AGG area; all factors strictly positive
- area and production rescale applied cell-by-cell across all three systems (max rel 9e-13)
- yield is unchanged, and production is consistent both with `area_rescaled × yield` and with
  `original production × factor`
- `AGG = IR + RF` survives the rescale for both area and production
- within-pid crop shares unchanged across all 7,263 (pid, crop) cells — max diff **6.3e-15**
- unanchored area and production are **bit-identical** to the originals (max diff **0.0**)
- the two pid sets partition `pid_used`; their records partition the original 17,994; no key
  outside the original support; `lumen_crop_unfilled` pids carry no AP area
