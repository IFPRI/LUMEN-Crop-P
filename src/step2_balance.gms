$title Step 2 - balance AP crop areas on the pid grid to LUMEN lu_out (per pid) and IMPACT AREACTYX0 (per crop and system)
$onEolCom

* Called by src/run.py with
*   --LU=<solution_lu.gdx> --CROP=<cty_crop_in_pid_coords.gdx> --TARGETS=<cty_impact_targets.gdx>
*   --OUT=<balanced.gdx> --BASEYEAR=<yyyy>
*
* lu_out is the ground truth. For every pid p in pid_run, crop j and system s in {IR, RF}:
*
*   rows     sum_{j,s} p_Area_lu(p,j,s)            = lu_out(p,'crop',BASEYEAR)                 (LUMEN, physical)
*   columns  sum_{p in cty} p_Area_harv(p,j,s)     = AREACTYX0(j,cty,s,BASEYEAR)               (IMPACT, harvested)
*   link     p_Area_harv(p,j,s)                    = p_Area_lu(p,j,s) * CROPINTENSX0(cty,BASEYEAR)
*   country  sum_p lu_out(p,'crop')                = sum_{j,s} AREACTYX0 / CROPINTENSX0  (= LANDX0 crop)   <- check 1
*
* RAS (iterative proportional fitting). Think of a table: one row per pid, one column per crop-system,
* hectares in the cells, filled by AP (the seed). LUMEN dictates every row total, IMPACT every column
* total (converted to physical hectares with CROPINTENSX0; check 1 makes the two grand totals agree).
* A row pass multiplies each row by (its target / its current sum), so all pid totals become right.
* A column pass multiplies each column by (its target / its current sum), so all crop-system totals
* become right and the rows drift a little. The passes alternate until both margins are within tol_ras
* (42 passes for KEN); one final row pass makes every pid total equal lu_out exactly (LUMEN has the
* last word, so the columns keep a residual of at most tol_ras). ras_row(pid) and ras_col(cty,j,s)
* accumulate every multiplier a row or column received, so on every AP cell
*     p_Area_lu(p,j,s) = seed(p,j,s) * ras_row(p) * ras_col(cty,j,s).
* Consequences: ratios inside a row (AP's crop mix on a pid) and inside a column (AP's spatial
* pattern of a crop) are preserved, only levels move; zeros stay zeros; and of all matrices with
* these margins the result is the closest to the seed (minimum cross-entropy), i.e. the smallest
* adjustment that satisfies both LUMEN and IMPACT.
*
* Where AP has nothing the seed is filled in and flagged (seed_source):
*   1  AP cell value                              the normal case
*   2  column fallback: AP has no area anywhere in the country for this crop-system (e.g. a crop
*      absent from AP's list) -> spread like AP's total area in that system (IR footprint for IR)
*   3  row fallback: the pid has LUMEN cropland but no usable AP crop mix -> the national IMPACT mix
* AP area that cannot be used is dropped and reported: pids outside pid_run, pids whose lu_out crop
* is zero, and crop-systems IMPACT has no area for.
*
* AP's p_Area is SPAM PHYSICAL area mapped to IMPACT crops (his export writes p_MapPhysP; there is no
* harvested layer), so AP production / AP area is a yield per PHYSICAL hectare. Production therefore
* follows physical area: p_Area_lu x (AP production / AP area) where AP has the cell (yield_source 1)
* or AP's country value for the crop-system (2); where neither exists IMPACT's YLDCTYX0, per harvested
* hectare, is applied to p_Area_harv (3). p_Yield_used is reported on one basis, t per harvested ha
* = production / p_Area_harv, so AP-based yields appear divided by the cropping intensity.

$if not set LU       $abort --LU=<solution_lu.gdx> is required
$if not set CROP     $abort --CROP=<cty_crop_in_pid_coords.gdx> is required
$if not set TARGETS  $abort --TARGETS=<cty_impact_targets.gdx> is required
$if not set OUT      $abort --OUT=<balanced.gdx> is required
$if not set BASEYEAR $abort --BASEYEAR=<yyyy> is required

* ---------------- LUMEN source ----------------
sets
   pid    'LUMEN 0.25-deg pixel IDs'
   cty    'countries'
   fland  'land pools'
   yrs    'years'
   coord  'coordinates' ;
set pid_run(pid)      'pixels in the countries LUMEN solved';
set cty_run(cty)      'countries LUMEN solved';
set pid_cty(pid,cty)  'pixel to country';
parameter lu_out(pid,fland,yrs) 'projected pixel land use by year (1000 ha)';

$gdxIn "%LU%"
$load pid cty fland yrs coord pid_run cty_run pid_cty lu_out
$gdxIn

abort$(not sum(yrs$sameas(yrs,'%BASEYEAR%'), 1)) 'BASEYEAR is not a year in solution_lu yrs', yrs;
abort$(not sum(fland$sameas(fland,'crop'), 1))   'solution_lu fland has no crop pool', fland;
abort$(card(cty_run) = 0)                        'solution_lu has an empty cty_run';

* ---------------- AP crop data on the pid grid (step 1) ----------------
sets
   PIXEL_S  'AP 5-arcmin pixel keys in the downscale file'
   JCROP    'crops (IMPACT j-codes)'
   SYS      'production system' ;
set PIXEL_UNMAPPED(PIXEL_S)        'AP pixels with no pid in the LUMEN land mask';
set pid_used(pid)                  'LUMEN pids carrying AP crop area';
set PIXEL_TO_PID_AP(PIXEL_S,pid)   'AP pixels of this file -> the LUMEN pid containing them';
parameters
   p_Area_pid(pid,JCROP,SYS)        'AP crop area on the LUMEN pid grid, untouched (1000 ha)'
   p_Production_pid(pid,JCROP,SYS)  'AP crop production on the LUMEN pid grid, untouched (1000 t)'
   pid_coords_used(pid,coord)       'cell-centre coords of the pids carrying AP crop area (deg)'
   n_ap_pix(pid)                    'AP 5-arcmin pixels feeding this pid (9 = fully covered)'
   p_Area_unmapped(PIXEL_UNMAPPED,JCROP,SYS)       'AP area on pixels with no pid (1000 ha)'
   p_Production_unmapped(PIXEL_UNMAPPED,JCROP,SYS) 'AP production on pixels with no pid (1000 t)' ;

$gdxIn "%CROP%"
$load PIXEL_S JCROP SYS PIXEL_UNMAPPED
$load pid_used PIXEL_TO_PID_AP p_Area_pid p_Production_pid pid_coords_used n_ap_pix
$load p_Area_unmapped p_Production_unmapped
$gdxIn

abort$(not sum(SYS$sameas(SYS,'AGG'), 1)) 'SYS has no AGG element', SYS;
abort$(not sum(SYS$sameas(SYS,'IR'), 1))  'SYS has no IR element', SYS;
abort$(not sum(SYS$sameas(SYS,'RF'), 1))  'SYS has no RF element', SYS;

* ---------------- IMPACT country targets (step 1b) ----------------
parameters
   area_harv_cty(cty,JCROP,SYS,yrs) 'IMPACT AREACTYX0: harvested area (1000 ha)'
   yield_cty(cty,JCROP,SYS,yrs)     'IMPACT YLDCTYX0: yield (t per harvested ha)'
   crop_intens(cty,yrs)             'IMPACT cropping intensity: harvested over physical'
   landx0_crop(cty,yrs)             'IMPACT LANDX0 crop: physical cropland (1000 ha)' ;

$gdxIn "%TARGETS%"
$loadDC area_harv_cty yield_cty crop_intens landx0_crop
$gdxIn

alias (pid,p), (JCROP,j), (SYS,s);
set s_bal(SYS) 'systems balanced: IR and RF; AGG is their sum';
s_bal(SYS) = yes$(not sameas(SYS,'AGG'));

scalar base_year 'LUMEN year used as the anchor' / %BASEYEAR% /;

* ================================================================ the two margins
parameter lu_out_crop_base(pid) 'row target: LUMEN lu_out(pid,crop,base_year) over pid_run (1000 ha)';
lu_out_crop_base(pid_run) = lu_out(pid_run,'crop','%BASEYEAR%');

parameter ci(cty) 'IMPACT cropping intensity at base_year';
ci(cty_run) = crop_intens(cty_run,'%BASEYEAR%');
abort$(sum(cty_run$(ci(cty_run) <= 0), 1)) 'cropping intensity missing or <= 0 for a cty_run country', ci;

parameter target_harv(cty,JCROP,SYS) 'column target, harvested: IMPACT AREACTYX0 at base_year (1000 ha)';
parameter target_lu(cty,JCROP,SYS)   'column target, physical: target_harv / cropping intensity, scaled by col_scale (1000 ha)';
target_harv(cty_run,j,s_bal) = area_harv_cty(cty_run,j,s_bal,'%BASEYEAR%');
target_lu(cty_run,j,s_bal)   = target_harv(cty_run,j,s_bal) / ci(cty_run);

* ---- CHECK 1: country totals. LUMEN crop == sum AREACTYX0 / CI (== LANDX0 crop where present)
parameters
   cty_lu_crop(cty)  'LUMEN: sum over pid_run of lu_out crop at base_year (1000 ha, physical)'
   cty_harv(cty)     'IMPACT: sum AREACTYX0 at base_year (1000 ha, harvested)'
   cty_phys(cty)     'IMPACT: sum AREACTYX0 / cropping intensity (1000 ha, physical)'
   cty_landx0(cty)   'IMPACT: LANDX0 crop at base_year (1000 ha, physical); 0 if the file has none'
   cty_gap_rel(cty)  '|LUMEN - IMPACT physical| / LUMEN'
   col_scale(cty)    'LUMEN total / IMPACT physical total, applied to the column targets so both margins sum to the same number' ;
cty_lu_crop(cty_run) = sum(pid_run$pid_cty(pid_run,cty_run), lu_out_crop_base(pid_run));
cty_harv(cty_run)    = sum((j,s_bal), target_harv(cty_run,j,s_bal));
cty_phys(cty_run)    = sum((j,s_bal), target_lu(cty_run,j,s_bal));
cty_landx0(cty_run)  = landx0_crop(cty_run,'%BASEYEAR%');
cty_gap_rel(cty_run)$cty_lu_crop(cty_run) = abs(cty_lu_crop(cty_run) - cty_phys(cty_run)) / cty_lu_crop(cty_run);

scalar tol_cty 'allowed relative gap between the LUMEN and IMPACT country crop totals' / 1e-6 /;
display cty_lu_crop, cty_harv, cty_phys, cty_landx0, cty_gap_rel;
abort$(sum(cty_run$(cty_lu_crop(cty_run) <= 0), 1)) 'a cty_run country has no lu_out crop at base_year', cty_lu_crop;
abort$(sum(cty_run$(cty_phys(cty_run) <= 0), 1))    'a cty_run country has no AREACTYX0 at base_year', cty_phys;
abort$(smax(cty_run, cty_gap_rel(cty_run)) > tol_cty)
   'CHECK 1 FAILED: LUMEN lu_out crop total differs from IMPACT sum AREACTYX0 / CROPINTENS', cty_lu_crop, cty_phys, cty_gap_rel;
col_scale(cty_run) = cty_lu_crop(cty_run) / cty_phys(cty_run);
target_lu(cty_run,j,s_bal) = target_lu(cty_run,j,s_bal) * col_scale(cty_run);

* ================================================================ rows and columns to balance
set pid_balanced(pid)          'pids balanced: in pid_run with lu_out crop > 0 at base_year';
set js_balanced(cty,JCROP,SYS) 'crop-system columns balanced: IMPACT AREACTYX0 > 0 at base_year';
pid_balanced(pid_run)$(lu_out_crop_base(pid_run) > 0) = yes;
js_balanced(cty_run,j,s_bal)$(target_lu(cty_run,j,s_bal) > 0) = yes;

parameter ap_agg(pid) 'AP crop area on the pid, all crops, SYS=AGG (1000 ha)';
ap_agg(pid) = sum(j, p_Area_pid(pid,j,'AGG'));

set pid_outside_run(pid)       'AP crop area on a pid outside pid_run (LUMEN assigns it to another country) - AP area dropped';
set pid_luzero(pid)            'AP crop area on a pid_run pid whose lu_out crop = 0 at base_year - AP area dropped';
set js_no_target(cty,JCROP,SYS) 'crop-systems AP reports but IMPACT has no area for - AP area dropped';
pid_outside_run(pid)$(ap_agg(pid) > 0 and not pid_run(pid)) = yes;
pid_luzero(pid)$(ap_agg(pid) > 0 and pid_run(pid) and not pid_balanced(pid)) = yes;
js_no_target(cty_run,j,s_bal)$(not js_balanced(cty_run,j,s_bal)
   and sum(pid_balanced$pid_cty(pid_balanced,cty_run), p_Area_pid(pid_balanced,j,s_bal)) > 0) = yes;

* ================================================================ the seed
parameter ap_usable(pid) 'AP area on the pid in crop-systems IMPACT has a target for (1000 ha)';
ap_usable(pid_balanced) = sum((cty_run,j,s_bal)$(pid_cty(pid_balanced,cty_run) and js_balanced(cty_run,j,s_bal)),
                              p_Area_pid(pid_balanced,j,s_bal));
set pid_seed_ap(pid)  'balanced pids seeded with the AP crop mix of the pid (seed_source 1, and 2 for unsupported columns)';
set pid_seed_nat(pid) 'balanced pids with no usable AP crop mix - seeded with the national IMPACT mix (seed_source 3)';
pid_seed_ap(pid_balanced)$(ap_usable(pid_balanced) > 0)  = yes;
pid_seed_nat(pid_balanced)$(ap_usable(pid_balanced) <= 0) = yes;

set js_seed_ap(cty,JCROP,SYS)  'balanced columns with AP support on at least one AP-seeded pid (seed_source 1)';
set js_seed_sys(cty,JCROP,SYS) 'balanced columns with no AP support anywhere in the country (seed_source 2)';
js_seed_ap(cty_run,j,s_bal)$(js_balanced(cty_run,j,s_bal)
   and sum(pid_seed_ap$pid_cty(pid_seed_ap,cty_run), p_Area_pid(pid_seed_ap,j,s_bal)) > 0) = yes;
js_seed_sys(cty_run,j,s_bal)$(js_balanced(cty_run,j,s_bal) and not js_seed_ap(cty_run,j,s_bal)) = yes;

parameter ap_sys(pid,SYS)     'AP crop area on the pid by system, all crops (1000 ha)';
parameter ap_sys_cty(cty,SYS) 'AP crop area by system over the AP-seeded pids of the country (1000 ha)';
ap_sys(pid,s_bal)         = sum(j, p_Area_pid(pid,j,s_bal));
ap_sys_cty(cty_run,s_bal) = sum(pid_seed_ap$pid_cty(pid_seed_ap,cty_run), ap_sys(pid_seed_ap,s_bal));

parameter nat_mix(cty,JCROP,SYS) 'national IMPACT crop-system shares of physical cropland at base_year';
nat_mix(cty_run,j,s_bal)$js_balanced(cty_run,j,s_bal)
   = target_lu(cty_run,j,s_bal) / sum((JCROP,SYS)$js_balanced(cty_run,JCROP,SYS), target_lu(cty_run,JCROP,SYS));

parameter seed(pid,JCROP,SYS)        'RAS seed (1000 ha)';
parameter seed_source(pid,JCROP,SYS) '1 = AP cell value, 2 = column fallback (AP system footprint), 3 = row fallback (national IMPACT mix)';
loop(cty_run,
*  1: AP's own values
   seed(pid_seed_ap,j,s_bal)$(pid_cty(pid_seed_ap,cty_run) and js_seed_ap(cty_run,j,s_bal))
      = p_Area_pid(pid_seed_ap,j,s_bal);
   seed_source(pid_seed_ap,j,s_bal)$(pid_cty(pid_seed_ap,cty_run) and js_seed_ap(cty_run,j,s_bal)
      and p_Area_pid(pid_seed_ap,j,s_bal) > 0) = 1;
*  2: columns AP knows nothing about: the column target spread like AP's area in that system,
*     or like lu_out if AP has no area in that system at all
   seed(pid_seed_ap,j,s_bal)$(pid_cty(pid_seed_ap,cty_run) and js_seed_sys(cty_run,j,s_bal))
      = target_lu(cty_run,j,s_bal)
        * ( (ap_sys(pid_seed_ap,s_bal) / ap_sys_cty(cty_run,s_bal))$(ap_sys_cty(cty_run,s_bal) > 0)
          + (lu_out_crop_base(pid_seed_ap) / cty_lu_crop(cty_run))$(ap_sys_cty(cty_run,s_bal) <= 0) );
   seed_source(pid_seed_ap,j,s_bal)$(pid_cty(pid_seed_ap,cty_run) and js_seed_sys(cty_run,j,s_bal)
      and seed(pid_seed_ap,j,s_bal) > 0) = 2;
*  3: pids AP knows nothing about: the pid's cropland split by the national IMPACT mix
   seed(pid_seed_nat,j,s_bal)$(pid_cty(pid_seed_nat,cty_run) and js_balanced(cty_run,j,s_bal))
      = lu_out_crop_base(pid_seed_nat) * nat_mix(cty_run,j,s_bal);
   seed_source(pid_seed_nat,j,s_bal)$(pid_cty(pid_seed_nat,cty_run) and js_balanced(cty_run,j,s_bal)
      and seed(pid_seed_nat,j,s_bal) > 0) = 3;
);

parameter row_seed(pid), col_seed(cty,JCROP,SYS);
row_seed(pid_balanced)      = sum((j,s_bal), seed(pid_balanced,j,s_bal));
col_seed(cty_run,j,s_bal)   = sum(pid_balanced$pid_cty(pid_balanced,cty_run), seed(pid_balanced,j,s_bal));
abort$(sum(pid_balanced$(row_seed(pid_balanced) <= 0), 1)) 'a balanced pid has an all-zero seed row', row_seed;
abort$(sum(js_balanced(cty_run,j,s_bal)$(col_seed(cty_run,j,s_bal) <= 0), 1)) 'a balanced column has an all-zero seed', col_seed;

* ================================================================ RAS
set iter 'RAS iterations' / i1*i20000 /;
scalar tol_ras 'converged when both margins are within this relative deviation' / 1e-10 /;
scalars dev_row 'max relative row deviation at the last iteration', dev_col 'max relative column deviation at the last iteration',
        n_iter 'RAS iterations used' / 0 /, converged / 0 /;
parameters
   A(pid,JCROP,SYS)             'the matrix being balanced (1000 ha)'
   rs(pid), rf(pid), cs(cty,JCROP,SYS), cf(cty,JCROP,SYS)
   ras_row(pid)                 'RAS pid factor: product of every row multiplier (lu_out / current pid sum) the pid received over all passes; p_Area_lu = seed x ras_row x ras_col on every seeded cell. Absorbs the harvested->physical conversion since the seed is in AP units'
   ras_col(cty,JCROP,SYS)       'RAS crop-system factor: product of every column multiplier (IMPACT target / current national sum) the crop-system received over all passes' ;
A(pid_balanced,j,s_bal) = seed(pid_balanced,j,s_bal);
ras_row(pid_balanced) = 1;
ras_col(cty_run,j,s_bal)$js_balanced(cty_run,j,s_bal) = 1;

loop(iter$(not converged),
*  rows to lu_out
   rs(pid_balanced) = sum((j,s_bal), A(pid_balanced,j,s_bal));
   rf(pid_balanced) = lu_out_crop_base(pid_balanced) / rs(pid_balanced);
   A(pid_balanced,j,s_bal) = A(pid_balanced,j,s_bal) * rf(pid_balanced);
   ras_row(pid_balanced)   = ras_row(pid_balanced) * rf(pid_balanced);
*  columns to the IMPACT targets, country by country
   cs(cty_run,j,s_bal)$js_balanced(cty_run,j,s_bal) = sum(pid_balanced$pid_cty(pid_balanced,cty_run), A(pid_balanced,j,s_bal));
   cf(cty_run,j,s_bal)$js_balanced(cty_run,j,s_bal) = target_lu(cty_run,j,s_bal) / cs(cty_run,j,s_bal);
   A(pid_balanced,j,s_bal) = A(pid_balanced,j,s_bal) * sum(cty_run$pid_cty(pid_balanced,cty_run), cf(cty_run,j,s_bal));
   ras_col(cty_run,j,s_bal)$js_balanced(cty_run,j,s_bal) = ras_col(cty_run,j,s_bal) * cf(cty_run,j,s_bal);
*  the columns are now exact; the rows carry the remaining deviation; cf says how far the columns were off
   dev_row = smax(pid_balanced, abs(sum((j,s_bal), A(pid_balanced,j,s_bal)) - lu_out_crop_base(pid_balanced)) / lu_out_crop_base(pid_balanced));
   dev_col = smax(js_balanced(cty_run,j,s_bal), abs(cf(cty_run,j,s_bal) - 1));
   n_iter = ord(iter);
   converged$(dev_row < tol_ras and dev_col < tol_ras) = 1;
);
abort$(not converged) 'RAS did not converge - the seed support cannot carry both margins', n_iter, dev_row, dev_col;

* lu_out has the last word: one more row scaling so every pid total equals lu_out to machine precision.
* The columns then differ from the IMPACT targets by at most tol_ras relative.
rs(pid_balanced) = sum((j,s_bal), A(pid_balanced,j,s_bal));
rf(pid_balanced) = lu_out_crop_base(pid_balanced) / rs(pid_balanced);
A(pid_balanced,j,s_bal) = A(pid_balanced,j,s_bal) * rf(pid_balanced);
ras_row(pid_balanced)   = ras_row(pid_balanced) * rf(pid_balanced);

* ================================================================ deliverables
parameters
   p_Area_lu(pid,JCROP,SYS)         'physical cropland by crop and system; sums over crops and IR+RF to lu_out(pid,crop,base_year) (1000 ha)'
   p_Area_harv(pid,JCROP,SYS)       'harvested area = p_Area_lu * cropping intensity; sums over pids to AREACTYX0(j,cty,sys,base_year) (1000 ha)'
   p_Yield_used(pid,JCROP,SYS)      'yield applied, t per harvested ha = p_Production_harv / p_Area_harv; AP yields are per physical ha and appear here divided by CI'
   yield_source(pid,JCROP,SYS)      '1 = AP cell yield (AP production / AP physical area on the pid), 2 = AP country yield for the crop-system, 3 = IMPACT YLDCTYX0'
   p_Production_harv(pid,JCROP,SYS) 'production (1000 t) = p_Area_lu x AP yield per physical ha (sources 1, 2) or p_Area_harv x YLDCTYX0 (3); always = p_Area_harv x p_Yield_used' ;

p_Area_lu(pid_balanced,j,s_bal) = A(pid_balanced,j,s_bal);
p_Area_lu(pid_balanced,j,'AGG') = sum(s_bal, A(pid_balanced,j,s_bal));
p_Area_harv(pid_balanced,j,SYS) = p_Area_lu(pid_balanced,j,SYS) * sum(cty_run$pid_cty(pid_balanced,cty_run), ci(cty_run));

parameter y_ap_cty(cty,JCROP,SYS) 'AP country yield: production over PHYSICAL area summed over the pids of the country (t per physical ha)';
y_ap_cty(cty_run,j,s_bal)$sum(pid$pid_cty(pid,cty_run), p_Area_pid(pid,j,s_bal))
   = sum(pid$pid_cty(pid,cty_run), p_Production_pid(pid,j,s_bal)) / sum(pid$pid_cty(pid,cty_run), p_Area_pid(pid,j,s_bal));

loop(cty_run,
   p_Yield_used(pid_balanced,j,s_bal)$(pid_cty(pid_balanced,cty_run) and A(pid_balanced,j,s_bal) > 0
      and p_Area_pid(pid_balanced,j,s_bal) > 0 and p_Production_pid(pid_balanced,j,s_bal) > 0)
      = p_Production_pid(pid_balanced,j,s_bal) / p_Area_pid(pid_balanced,j,s_bal) / ci(cty_run);    !! per physical ha -> per harvested ha
   yield_source(pid_balanced,j,s_bal)$(pid_cty(pid_balanced,cty_run) and p_Yield_used(pid_balanced,j,s_bal) > 0) = 1;
   p_Yield_used(pid_balanced,j,s_bal)$(pid_cty(pid_balanced,cty_run) and A(pid_balanced,j,s_bal) > 0
      and yield_source(pid_balanced,j,s_bal) = 0 and y_ap_cty(cty_run,j,s_bal) > 0)
      = y_ap_cty(cty_run,j,s_bal) / ci(cty_run);    !! per physical ha -> per harvested ha
   yield_source(pid_balanced,j,s_bal)$(pid_cty(pid_balanced,cty_run) and p_Yield_used(pid_balanced,j,s_bal) > 0
      and yield_source(pid_balanced,j,s_bal) = 0) = 2;
   p_Yield_used(pid_balanced,j,s_bal)$(pid_cty(pid_balanced,cty_run) and A(pid_balanced,j,s_bal) > 0
      and yield_source(pid_balanced,j,s_bal) = 0)
      = yield_cty(cty_run,j,s_bal,'%BASEYEAR%');
   yield_source(pid_balanced,j,s_bal)$(pid_cty(pid_balanced,cty_run) and p_Yield_used(pid_balanced,j,s_bal) > 0
      and yield_source(pid_balanced,j,s_bal) = 0) = 3;
);
abort$(sum((pid_balanced,j,s_bal)$(A(pid_balanced,j,s_bal) > 0 and p_Yield_used(pid_balanced,j,s_bal) <= 0), 1))
   'an allocated cell has no yield from AP or IMPACT', p_Yield_used;

* on AP-based cells this equals p_Area_lu x AP yield per physical ha, since p_Area_harv = p_Area_lu x ci
p_Production_harv(pid_balanced,j,s_bal) = p_Area_harv(pid_balanced,j,s_bal) * p_Yield_used(pid_balanced,j,s_bal);
p_Production_harv(pid_balanced,j,'AGG') = sum(s_bal, p_Production_harv(pid_balanced,j,s_bal));
p_Yield_used(pid_balanced,j,'AGG')$p_Area_harv(pid_balanced,j,'AGG')
   = p_Production_harv(pid_balanced,j,'AGG') / p_Area_harv(pid_balanced,j,'AGG');

* ---------------- AP area that could not be used ----------------
parameters
   p_Area_ap_dropped(pid,JCROP,SYS)       'AP area not used as seed: pid outside pid_run, lu_out crop = 0, or no IMPACT target for the crop-system (1000 ha)'
   p_Production_ap_dropped(pid,JCROP,SYS) 'AP production on those cells (1000 t)' ;
p_Area_ap_dropped(pid,j,s_bal)$(p_Area_pid(pid,j,s_bal) > 0 and seed_source(pid,j,s_bal) <> 1) = p_Area_pid(pid,j,s_bal);
p_Production_ap_dropped(pid,j,s_bal)$p_Area_ap_dropped(pid,j,s_bal) = p_Production_pid(pid,j,s_bal);
p_Area_ap_dropped(pid,j,'AGG')       = sum(s_bal, p_Area_ap_dropped(pid,j,s_bal));
p_Production_ap_dropped(pid,j,'AGG') = sum(s_bal, p_Production_ap_dropped(pid,j,s_bal));

* ================================================================ checks
scalars
   worst_row  'max relative gap: per-pid sum of p_Area_lu vs lu_out crop'
   worst_col  'max relative gap: per crop-system sum of p_Area_harv vs AREACTYX0 (x col_scale)'
   tot_lu     'sum of p_Area_lu, AGG (1000 ha)'
   tot_lumen  'sum of lu_out crop over pid_run (1000 ha)'
   tot_harv   'sum of p_Area_harv, AGG (1000 ha)'
   tot_impact 'sum of AREACTYX0 (1000 ha)'
   tot_prod   'sum of p_Production_harv, AGG (1000 t)'
   ap_in      'AP area on the pid grid, AGG (1000 ha)'
   ap_seeded  'AP area used as seed, IR+RF (1000 ha)'
   ap_dropped 'AP area dropped, AGG (1000 ha)'
   n_pid_bal, n_pid_seed_ap, n_pid_seed_nat, n_pid_outside_run, n_pid_luzero
   n_col_bal, n_col_seed_ap, n_col_seed_sys, n_col_no_target ;

worst_row  = smax(pid_balanced, abs(sum(j, p_Area_lu(pid_balanced,j,'AGG')) - lu_out_crop_base(pid_balanced)) / lu_out_crop_base(pid_balanced));
worst_col  = smax(js_balanced(cty_run,j,s_bal),
                abs(sum(pid_balanced$pid_cty(pid_balanced,cty_run), p_Area_harv(pid_balanced,j,s_bal))
                    - target_harv(cty_run,j,s_bal) * col_scale(cty_run)) / (target_harv(cty_run,j,s_bal) * col_scale(cty_run)));
tot_lu     = sum((pid_balanced,j), p_Area_lu(pid_balanced,j,'AGG'));
tot_lumen  = sum(cty_run, cty_lu_crop(cty_run));
tot_harv   = sum((pid_balanced,j), p_Area_harv(pid_balanced,j,'AGG'));
tot_impact = sum(cty_run, cty_harv(cty_run));
tot_prod   = sum((pid_balanced,j), p_Production_harv(pid_balanced,j,'AGG'));
ap_in      = sum(pid, ap_agg(pid));
ap_seeded  = sum((pid,j,s_bal)$(seed_source(pid,j,s_bal) = 1), p_Area_pid(pid,j,s_bal));
ap_dropped = sum((pid,j), p_Area_ap_dropped(pid,j,'AGG'));
n_pid_bal = card(pid_balanced);  n_pid_seed_ap = card(pid_seed_ap);  n_pid_seed_nat = card(pid_seed_nat);
n_pid_outside_run = card(pid_outside_run);  n_pid_luzero = card(pid_luzero);
n_col_bal = card(js_balanced);  n_col_seed_ap = card(js_seed_ap);  n_col_seed_sys = card(js_seed_sys);  n_col_no_target = card(js_no_target);

display base_year, n_iter, dev_row, dev_col, worst_row, worst_col, tot_lu, tot_lumen, tot_harv, tot_impact, tot_prod,
        ap_in, ap_seeded, ap_dropped, n_pid_bal, n_pid_seed_ap, n_pid_seed_nat, n_pid_outside_run, n_pid_luzero,
        n_col_bal, n_col_seed_ap, n_col_seed_sys, n_col_no_target;

abort$(worst_row > 1e-12)        'per-pid p_Area_lu does not reproduce lu_out crop', worst_row;
abort$(worst_col > 10 * tol_ras) 'per crop-system p_Area_harv does not reproduce AREACTYX0', worst_col;
abort$(abs(ap_in - ap_seeded - ap_dropped) > 1e-6) 'AP area is not fully accounted for as seeded + dropped', ap_in, ap_seeded, ap_dropped;
abort$(sum((pid,j,s)$(p_Area_lu(pid,j,s) < 0 or p_Area_harv(pid,j,s) < 0 or p_Production_harv(pid,j,s) < 0), 1)) 'negative value in a deliverable';

execute_unload '%OUT%',
   pid, cty, PIXEL_S, JCROP, SYS, coord, PIXEL_UNMAPPED, base_year, s_bal,
   pid_run, cty_run, pid_cty, pid_used,
   pid_balanced, pid_seed_ap, pid_seed_nat, pid_outside_run, pid_luzero,
   js_balanced, js_seed_ap, js_seed_sys, js_no_target,
   PIXEL_TO_PID_AP, pid_coords_used, n_ap_pix,
   p_Area_pid, p_Production_pid,
   p_Area_lu, p_Area_harv, p_Production_harv, p_Yield_used, yield_source,
   seed, seed_source, ras_row, ras_col, n_iter,
   lu_out_crop_base, target_harv, target_lu, ci, col_scale,
   cty_lu_crop, cty_harv, cty_phys, cty_landx0, cty_gap_rel,
   p_Area_ap_dropped, p_Production_ap_dropped,
   p_Area_unmapped, p_Production_unmapped;
