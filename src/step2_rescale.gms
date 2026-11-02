$title Step 2 - rescale AP pid-level crop area/production to match LUMEN lu_out(pid,'crop',BASEYEAR)
$onEolCom

* Called by src/run.py with
*   --LU=<solution_lu.gdx>  --CROP=<cty_crop_in_pid_coords.gdx>  --OUT=<rescaled.gdx>  --BASEYEAR=<yyyy>
*
* Per pid p, over the crops j and systems s in {AGG, IR, RF}:
*     p_Yield_rescaled(p,j,s)      = p_Production_pid(p,j,s) / p_Area_pid(p,j,s)      [t/ha]
*     anchor(p)                    = lu_out(p,'crop',BASEYEAR)                        [kha]
*     rescale_factor(p)            = anchor(p) / sum_j p_Area_pid(p,j,'AGG')
*     p_Area_rescaled(p,j,s)       = p_Area_pid(p,j,s) * rescale_factor(p)            [kha]
*     p_Production_rescaled(p,j,s) = p_Area_rescaled(p,j,s) * p_Yield_rescaled(p,j,s) [kt]
*
* Yield is held fixed, so the rescale moves area and production by the same factor and leaves
* the within-pid crop mix untouched. Pids with AP crop area but no usable lu_out anchor are NOT
* scaled: they keep their original values in the *_unanchored parameters and are flagged. Pids
* where LUMEN reports crop area but AP supplies no crop composition are reported in
* lumen_crop_unfilled and deliberately left unfilled -- nothing is synthesised.

$if not set LU       $abort --LU=<solution_lu.gdx> is required
$if not set CROP     $abort --CROP=<cty_crop_in_pid_coords.gdx> is required
$if not set OUT      $abort --OUT=<rescaled.gdx> is required
$if not set BASEYEAR $abort --BASEYEAR=<yyyy> is required

* ---------------- LUMEN source ----------------
sets
   pid    'LUMEN 0.25-deg pixel IDs'
   fland  'land pools'
   yrs    'years'
   coord  'coordinates' ;
set pid_run(pid) 'pixels in the countries LUMEN solved';
parameter lu_out(pid,fland,yrs) 'projected pixel land use by year (1000 ha)';

$gdxIn "%LU%"
$load pid fland yrs coord pid_run lu_out
$gdxIn

abort$(not sum(yrs$sameas(yrs,'%BASEYEAR%'), 1))
   'BASEYEAR is not a year in solution_lu yrs', yrs;
abort$(not sum(fland$sameas(fland,'crop'), 1))
   'solution_lu fland has no crop pool', fland;

* ---------------- AP crop data already on the pid grid (step 1) ----------------
sets
   PIXEL_S                 'AP 5-arcmin pixel keys in the downscale file'
   JCROP                   'crops'
   SYS                     'production system' ;
set PIXEL_UNMAPPED(PIXEL_S)        'AP pixels with no pid in the LUMEN land mask';
set pid_used(pid)                  'LUMEN pids carrying AP crop area';
set PIXEL_TO_PID_AP(PIXEL_S,pid)   'AP pixels of this file -> the LUMEN pid containing them';
parameters
   p_Area_pid(pid,JCROP,SYS)        'AP crop area on the LUMEN pid grid (1000 ha)'
   p_Production_pid(pid,JCROP,SYS)  'AP crop production on the LUMEN pid grid (1000 t)'
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

alias (pid,p);

scalar base_year 'LUMEN year used as the rescale anchor' / %BASEYEAR% /;

* ---------------- yield first, from the untouched originals ----------------
parameter p_Yield_rescaled(pid,JCROP,SYS) 'implied yield, production over area - invariant under the rescale (t per ha)';
p_Yield_rescaled(p,JCROP,SYS)$p_Area_pid(p,JCROP,SYS)
   = p_Production_pid(p,JCROP,SYS) / p_Area_pid(p,JCROP,SYS);

abort$(card(p_Yield_rescaled) <> card(p_Area_pid))
   'a non-zero area cell produced no yield - check for zero areas', p_Yield_rescaled;

* ---------------- classify pids ----------------
parameter ap_agg(pid)            'AP total crop area on this pid, SYS=AGG (1000 ha)';
parameter lu_out_crop_base(pid)  'LUMEN lu_out(pid,crop,base_year), the rescale target (1000 ha)';
ap_agg(p)           = sum(JCROP, p_Area_pid(p,JCROP,'AGG'));
lu_out_crop_base(p) = lu_out(p,'crop','%BASEYEAR%');

set pid_rescaled(pid)    'pids whose AP crop areas were rescaled to the lu_out crop anchor';
set pid_unanchored(pid)  'pids with AP crop area but no usable lu_out anchor - preserved unscaled';
set pid_outside_run(pid) 'subset of pid_unanchored: outside pid_run, so no lu_out at all';
set pid_luzero(pid)      'subset of pid_unanchored: inside pid_run but lu_out crop = 0';
set pid_lumen_only(pid)  'pids where LUMEN reports crop but AP has no crop mix - left unfilled';

pid_rescaled(p)    = yes$(ap_agg(p) > 0 and lu_out_crop_base(p) > 0);
pid_unanchored(p)  = yes$(ap_agg(p) > 0 and not pid_rescaled(p));
pid_outside_run(p) = yes$(pid_unanchored(p) and not pid_run(p));
pid_luzero(p)      = yes$(pid_unanchored(p) and pid_run(p));
pid_lumen_only(p)  = yes$(ap_agg(p) <= 0 and lu_out_crop_base(p) > 0);

* ---------------- the rescale ----------------
parameter rescale_factor(pid) 'lu_out crop base_year over AP AGG crop area - applied to area and production alike';
rescale_factor(pid_rescaled) = lu_out_crop_base(pid_rescaled) / ap_agg(pid_rescaled);

parameter p_Area_rescaled(pid,JCROP,SYS)       'AP crop area rescaled so each pid sums to lu_out crop base_year (1000 ha)';
parameter p_Production_rescaled(pid,JCROP,SYS) 'production consistent with the rescaled area at unchanged yield (1000 t)';

p_Area_rescaled(pid_rescaled,JCROP,SYS)
   = p_Area_pid(pid_rescaled,JCROP,SYS) * rescale_factor(pid_rescaled);
p_Production_rescaled(pid_rescaled,JCROP,SYS)
   = p_Area_rescaled(pid_rescaled,JCROP,SYS) * p_Yield_rescaled(pid_rescaled,JCROP,SYS);

* ---------------- preserved, unscaled ----------------
parameters
   p_Area_unanchored(pid,JCROP,SYS)       'AP area on unanchored pids - ORIGINAL, not rescaled (1000 ha)'
   p_Production_unanchored(pid,JCROP,SYS) 'AP production on unanchored pids - ORIGINAL, not rescaled (1000 t)'
   p_Yield_unanchored(pid,JCROP,SYS)      'implied yield on unanchored pids (t/ha)'
   lumen_crop_unfilled(pid)               'LUMEN crop on pids with no AP crop mix - NOT allocated (1000 ha)' ;

p_Area_unanchored(pid_unanchored,JCROP,SYS)       = p_Area_pid(pid_unanchored,JCROP,SYS);
p_Production_unanchored(pid_unanchored,JCROP,SYS) = p_Production_pid(pid_unanchored,JCROP,SYS);
p_Yield_unanchored(pid_unanchored,JCROP,SYS)      = p_Yield_rescaled(pid_unanchored,JCROP,SYS);
lumen_crop_unfilled(pid_lumen_only)               = lu_out_crop_base(pid_lumen_only);

* ---------------- checks ----------------
scalar tol / 1e-9 /;
scalar worst_gap, worst_rel, tot_r, tot_anchor, tot_u, n_bad, n_part, n_split, n_orig;

worst_gap = smax(pid_rescaled,
              abs(sum(JCROP, p_Area_rescaled(pid_rescaled,JCROP,'AGG'))
                  - lu_out_crop_base(pid_rescaled)));
worst_rel = smax(pid_rescaled,
              abs(sum(JCROP, p_Area_rescaled(pid_rescaled,JCROP,'AGG'))
                  - lu_out_crop_base(pid_rescaled)) / lu_out_crop_base(pid_rescaled));
tot_r      = sum((pid_rescaled,JCROP), p_Area_rescaled(pid_rescaled,JCROP,'AGG'));
tot_anchor = sum(pid_rescaled, lu_out_crop_base(pid_rescaled));
tot_u      = sum((pid_unanchored,JCROP), p_Area_unanchored(pid_unanchored,JCROP,'AGG'));
n_bad      = sum(pid_rescaled$(rescale_factor(pid_rescaled) <= 0), 1);
n_part     = card(pid_rescaled) + card(pid_unanchored);
n_orig     = card(pid_used);
n_split    = card(p_Area_rescaled) + card(p_Area_unanchored);

display base_year, worst_gap, worst_rel, tot_r, tot_anchor, tot_u, n_bad, n_part, n_orig, n_split;

abort$(worst_rel > tol) 'per-pid rescaled area does not match the lu_out anchor', worst_rel;
abort$(n_bad > 0)       'non-positive rescale factor on a rescaled pid', n_bad;
abort$(n_part <> n_orig)
   'pid_rescaled and pid_unanchored do not partition pid_used', n_part, n_orig;
abort$(n_split <> card(p_Area_pid))
   'rescaled + unanchored records do not account for every original record', n_split;

execute_unload '%OUT%',
   pid, PIXEL_S, JCROP, SYS, coord, PIXEL_UNMAPPED, base_year,
   pid_used, pid_rescaled, pid_unanchored, pid_outside_run, pid_luzero, pid_lumen_only,
   PIXEL_TO_PID_AP, pid_coords_used, n_ap_pix,
   p_Area_pid, p_Production_pid,
   p_Area_rescaled, p_Production_rescaled, p_Yield_rescaled,
   p_Area_unanchored, p_Production_unanchored, p_Yield_unanchored,
   rescale_factor, lu_out_crop_base, lumen_crop_unfilled,
   p_Area_unmapped, p_Production_unmapped;
