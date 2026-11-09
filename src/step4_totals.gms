$title Step 4 - country totals, land totals and yields at every stage of the pipeline
$onEolCom

* Called by src/run.py (or by hand) with
*   gams src/step4_totals.gms pf=output/secondary/step4_totals.pf
* where the parameter file holds
*   --AP=<AP downscale gdx> --LU=<solution_lu.gdx> --CROP=<cty_crop_in_pid_coords.gdx>
*   --TARGETS=<cty_impact_targets.gdx> --BAL=<cty_crop_in_pid_coords_balanced.gdx>
*   --OUT=<cty_totals.gdx> --BASEYEAR=<yyyy>
*
* The tables are displayed (listing output/secondary/step4_totals.lst, echoed to the console by
* run.py) and unloaded unchanged to the --OUT GDX. Nothing in the pipeline reads that GDX.
*
*   crop_tot(stage,cty,SYS,metric)   area (1000 ha), production (1000 t) and yield (t/ha) by country at each stage
*   crop_cmp(cty,JCROP,SYS,item)     per crop and system: AP, IMPACT and balanced area, production and yield,
*                                    the dropped AP area and the ratios (see set item), plus an ALL_CROPS row
*   yld_summary(cty,ydev)            how close the balanced yields are to AP and to IMPACT
*   pid_check(pid,rchk)              every pid in pid_run: lu_out crop vs balanced physical area, difference, relative difference
*   cs_check(cty,JCROP,SYS,cchk)     every crop-system: IMPACT AREACTYX0 vs balanced harvested area, difference, relative difference
*   margin_check(cty,mchk)           worst case of both, and how many rows or columns are off by more than 1e-9
*   land_tot(cty,fland,source)       land by pool at BASEYEAR: LUMEN lu_out over pid_run, LUMEN lu_cty, IMPACT control
*   land_by_year(cty,fland,yrs)      LUMEN lu_out by pool and year over pid_run
*
* Rows are the countries in cty_run (LUMEN's pid_cty decides which pid belongs to which country) plus
*   other_cty  AP area on pids LUMEN assigns to a country not in cty_run (all of it is dropped in step 2)
*   ALL        everything, including the raw AP file and the unmapped residual, which have no pid
* Bases: AP's p_Area is SPAM PHYSICAL area mapped to IMPACT crops (his export has no harvested layer);
* LUMEN lu_out is physical; IMPACT AREACTYX0 is harvested. AP's file has no yield: AP production / AP
* area is a yield per PHYSICAL ha. Wherever an AP yield is set beside IMPACT's or the balanced one
* (both per harvested ha) it is divided by the national cropping intensity first.

$if not set AP       $abort --AP=<AP downscale gdx> is required
$if not set LU       $abort --LU=<solution_lu.gdx> is required
$if not set CROP     $abort --CROP=<cty_crop_in_pid_coords.gdx> is required
$if not set TARGETS  $abort --TARGETS=<cty_impact_targets.gdx> is required
$if not set BAL      $abort --BAL=<balanced.gdx> is required
$if not set OUT      $abort --OUT=<cty_totals.gdx> is required
$if not set BASEYEAR $abort --BASEYEAR=<yyyy> is required

* ---------------- LUMEN ----------------
sets pid 'LUMEN 0.25-deg pixel IDs', cty 'countries', fland 'land pools', yrs 'years';
sets pid_run(pid), cty_run(cty), pid_cty(pid,cty);
parameters
   lu_out(pid,fland,yrs)        'projected pixel land use by year (1000 ha)'
   lu_cty(cty,fland,yrs)        'LUMEN pixel sums by country pool and year (1000 ha)'
   impact_total(cty,fland,yrs)  'IMPACT control totals (1000 ha)' ;
$gdxIn "%LU%"
$load pid cty fland yrs pid_run cty_run pid_cty lu_out
$loadDC lu_cty impact_total
$gdxIn
abort$(not sum(yrs$sameas(yrs,'%BASEYEAR%'), 1)) 'BASEYEAR is not a year in solution_lu yrs', yrs;

* ---------------- AP on the pid grid (step 1) and IMPACT targets (step 1b) ----------------
sets JCROP 'crops (IMPACT j-codes)', SYS 'production system', PIXEL_S 'AP pixel keys', PIXEL_UNMAPPED(PIXEL_S);
parameters
   p_Area_pid(pid,JCROP,SYS)                        'AP crop area on the pid grid (1000 ha, PHYSICAL)'
   p_Production_pid(pid,JCROP,SYS)                  'AP crop production on the pid grid (1000 t)'
   p_Area_unmapped(PIXEL_UNMAPPED,JCROP,SYS)        'AP area on pixels with no pid (1000 ha)'
   p_Production_unmapped(PIXEL_UNMAPPED,JCROP,SYS)  'AP production on pixels with no pid (1000 t)' ;
$gdxIn "%CROP%"
$load JCROP SYS PIXEL_S PIXEL_UNMAPPED
$loadDC p_Area_pid p_Production_pid p_Area_unmapped p_Production_unmapped
$gdxIn

parameters
   area_harv_cty(cty,JCROP,SYS,yrs) 'IMPACT AREACTYX0: harvested area (1000 ha)'
   yield_cty(cty,JCROP,SYS,yrs)     'IMPACT YLDCTYX0: yield (t per harvested ha)'
   crop_intens(cty,yrs)             'IMPACT cropping intensity: harvested over physical'
   landx0_crop(cty,yrs)             'IMPACT LANDX0 crop: physical cropland (1000 ha)' ;
$gdxIn "%TARGETS%"
$loadDC area_harv_cty yield_cty crop_intens landx0_crop
$gdxIn

* ---------------- AP source file (step 0) ----------------
set PIXEL_RAW 'pixel keys in the AP source file';
parameters p_Area_raw(PIXEL_RAW,JCROP,SYS), p_Production_raw(PIXEL_RAW,JCROP,SYS);
$gdxIn "%AP%"
$load PIXEL_RAW<p_Area.dim1
$loadDC p_Area_raw=p_Area p_Production_raw=p_Production
$gdxIn

* ---------------- balanced result (step 2) ----------------
parameters
   p_Area_lu(pid,JCROP,SYS)               'balanced physical cropland (1000 ha)'
   p_Area_harv(pid,JCROP,SYS)             'balanced harvested area (1000 ha)'
   p_Production_harv(pid,JCROP,SYS)       'balanced production (1000 t)'
   p_Area_ap_dropped(pid,JCROP,SYS)       'AP area not used as seed (1000 ha)'
   p_Production_ap_dropped(pid,JCROP,SYS) 'AP production on those cells (1000 t)' ;
$gdxIn "%BAL%"
$loadDC p_Area_lu p_Area_harv p_Production_harv p_Area_ap_dropped p_Production_ap_dropped
$gdxIn

alias (SYS,s);
set s_bal(SYS) 'IR and RF; AGG is their sum';
s_bal(SYS) = yes$(not sameas(SYS,'AGG'));

* ================================================================ crop totals by stage
set stage 'pipeline stage' /
   s0_AP_file          'AP source file, all pixels (PHYSICAL area; yield = prod / (area x CI))'
   s1_AP_on_pid_grid   'step 1: AP summed onto LUMEN pids (PHYSICAL area; yield = prod / (area x CI))'
   s1_AP_unmapped      'step 1: AP pixels outside the LUMEN land mask (PHYSICAL area)'
   s1b_IMPACT_harv     'step 1b: IMPACT AREACTYX0 at BASEYEAR (harvested); production = area x YLDCTYX0'
   s1b_IMPACT_phys     'step 1b: IMPACT AREACTYX0 / CROPINTENSX0 (physical)'
   s1b_IMPACT_LANDX0   'step 1b: IMPACT LANDX0 crop at BASEYEAR (physical)'
   s2_LUMEN_lu_out     'step 2 row target: LUMEN lu_out crop at BASEYEAR over pid_run (physical)'
   s2_balanced_phys    'step 2: balanced p_Area_lu (physical)'
   s2_balanced_harv    'step 2: balanced p_Area_harv and p_Production_harv (harvested)'
   s2_AP_dropped       'step 2: AP area on pids outside pid_run, lu_out-zero pids or no-target crop-systems' /;
set metric / area 'area (1000 ha)', prod 'production (1000 t)', yield 'production per harvested ha (t/ha); on AP rows prod / (physical area x CI)' /;

* pids with AP area that LUMEN assigns to a country outside cty_run
set pid_other(pid) 'pids carrying AP area whose LUMEN country is not in cty_run';
pid_other(pid)$(sum(JCROP, p_Area_pid(pid,JCROP,'AGG')) > 0 and not sum(cty_run$pid_cty(pid,cty_run), 1)) = yes;

* the country index is cty_run + other_cty + ALL, so it is declared on the universe
parameter crop_tot(stage,*,SYS,metric) 'country totals of crop area (1000 ha), production (1000 t) and yield (t/ha) at each stage';

crop_tot('s0_AP_file','ALL',SYS,'area') = sum((PIXEL_RAW,JCROP), p_Area_raw(PIXEL_RAW,JCROP,SYS));
crop_tot('s0_AP_file','ALL',SYS,'prod') = sum((PIXEL_RAW,JCROP), p_Production_raw(PIXEL_RAW,JCROP,SYS));

crop_tot('s1_AP_on_pid_grid',cty_run,SYS,'area')     = sum((pid,JCROP)$pid_cty(pid,cty_run), p_Area_pid(pid,JCROP,SYS));
crop_tot('s1_AP_on_pid_grid',cty_run,SYS,'prod')     = sum((pid,JCROP)$pid_cty(pid,cty_run), p_Production_pid(pid,JCROP,SYS));
crop_tot('s1_AP_on_pid_grid','other_cty',SYS,'area') = sum((pid_other,JCROP), p_Area_pid(pid_other,JCROP,SYS));
crop_tot('s1_AP_on_pid_grid','other_cty',SYS,'prod') = sum((pid_other,JCROP), p_Production_pid(pid_other,JCROP,SYS));
crop_tot('s1_AP_unmapped','ALL',SYS,'area')          = sum((PIXEL_UNMAPPED,JCROP), p_Area_unmapped(PIXEL_UNMAPPED,JCROP,SYS));
crop_tot('s1_AP_unmapped','ALL',SYS,'prod')          = sum((PIXEL_UNMAPPED,JCROP), p_Production_unmapped(PIXEL_UNMAPPED,JCROP,SYS));

crop_tot('s1b_IMPACT_harv',cty_run,SYS,'area') = sum(JCROP, area_harv_cty(cty_run,JCROP,SYS,'%BASEYEAR%'));
crop_tot('s1b_IMPACT_harv',cty_run,s_bal,'prod')
   = sum(JCROP, area_harv_cty(cty_run,JCROP,s_bal,'%BASEYEAR%') * yield_cty(cty_run,JCROP,s_bal,'%BASEYEAR%'));
crop_tot('s1b_IMPACT_harv',cty_run,'AGG','prod') = sum(s_bal, crop_tot('s1b_IMPACT_harv',cty_run,s_bal,'prod'));
crop_tot('s1b_IMPACT_phys',cty_run,SYS,'area')$crop_intens(cty_run,'%BASEYEAR%')
   = crop_tot('s1b_IMPACT_harv',cty_run,SYS,'area') / crop_intens(cty_run,'%BASEYEAR%');
crop_tot('s1b_IMPACT_LANDX0',cty_run,'AGG','area') = landx0_crop(cty_run,'%BASEYEAR%');

crop_tot('s2_LUMEN_lu_out',cty_run,'AGG','area')  = sum(pid_run$pid_cty(pid_run,cty_run), lu_out(pid_run,'crop','%BASEYEAR%'));
crop_tot('s2_balanced_phys',cty_run,SYS,'area')   = sum((pid,JCROP)$pid_cty(pid,cty_run), p_Area_lu(pid,JCROP,SYS));
crop_tot('s2_balanced_harv',cty_run,SYS,'area')   = sum((pid,JCROP)$pid_cty(pid,cty_run), p_Area_harv(pid,JCROP,SYS));
crop_tot('s2_balanced_harv',cty_run,SYS,'prod')   = sum((pid,JCROP)$pid_cty(pid,cty_run), p_Production_harv(pid,JCROP,SYS));
crop_tot('s2_AP_dropped',cty_run,SYS,'area')      = sum((pid,JCROP)$pid_cty(pid,cty_run), p_Area_ap_dropped(pid,JCROP,SYS));
crop_tot('s2_AP_dropped',cty_run,SYS,'prod')      = sum((pid,JCROP)$pid_cty(pid,cty_run), p_Production_ap_dropped(pid,JCROP,SYS));
crop_tot('s2_AP_dropped','other_cty',SYS,'area')  = sum((pid_other,JCROP), p_Area_ap_dropped(pid_other,JCROP,SYS));
crop_tot('s2_AP_dropped','other_cty',SYS,'prod')  = sum((pid_other,JCROP), p_Production_ap_dropped(pid_other,JCROP,SYS));

* ALL = cty_run + other_cty for the stages attributed by pid
crop_tot(stage,'ALL',SYS,metric)$(not sameas(stage,'s0_AP_file') and not sameas(stage,'s1_AP_unmapped') and not sameas(metric,'yield'))
   = sum(cty_run, crop_tot(stage,cty_run,SYS,metric)) + crop_tot(stage,'other_cty',SYS,metric);

* aggregate yield of each stage = production / area; empty where a stage has no production (physical-area stages)
set rowc 'rows of crop_tot' / other_cty, ALL /;
rowc(cty_run) = yes;
crop_tot(stage,rowc,SYS,'yield')$(crop_tot(stage,rowc,SYS,'area') > 0 and crop_tot(stage,rowc,SYS,'prod') > 0)
   = crop_tot(stage,rowc,SYS,'prod') / crop_tot(stage,rowc,SYS,'area');
* AP rows hold physical area: per physical ha -> per harvested-equivalent ha with the cropping intensity (one cty_run country per run)
set stage_ap(stage) 'stages whose area is AP physical area' / s0_AP_file, s1_AP_on_pid_grid, s1_AP_unmapped, s2_AP_dropped /;
crop_tot(stage_ap,rowc,SYS,'yield')$crop_tot(stage_ap,rowc,SYS,'yield')
   = crop_tot(stage_ap,rowc,SYS,'yield') / smax(cty_run, crop_intens(cty_run,'%BASEYEAR%'));

* ================================================================ crop-specific comparison: AP vs IMPACT vs balanced
* One row per crop and system (plus ALL_CROPS), one column per item. Area in 1000 ha, production in
* 1000 t, yield in t/ha. AP area is PHYSICAL and is compared with the balanced physical area; IMPACT
* AREACTYX0 is harvested and is compared with the balanced harvested area. IMPACT production =
* AREACTYX0 x YLDCTYX0. AP yield is shown per physical ha and per harvested-equivalent ha (/ CI).
set item 'columns of crop_cmp' /
   AP_area     'AP PHYSICAL area on the pids of the country (step 1 grid), 1000 ha'
   bal_phys    'balanced p_Area_lu (PHYSICAL), 1000 ha'
   bal_to_AP   'bal_phys / AP_area: what the balance did to AP area'
   IMP_area    'IMPACT AREACTYX0 at BASEYEAR (HARVESTED), 1000 ha'
   bal_harv    'balanced p_Area_harv (HARVESTED; equals IMP_area by construction), 1000 ha'
   AP_dropped  'AP area of this crop-system on the country pids that could not be used, 1000 ha'
   AP_prod     'AP production, 1000 t'
   IMP_prod    'IMPACT production = AREACTYX0 x YLDCTYX0, 1000 t'
   bal_prod    'balanced p_Production_harv, 1000 t'
   AP_yld_ph   'AP yield per PHYSICAL ha = AP_prod / AP_area'
   AP_yld      'AP yield per harvested-equivalent ha = AP_yld_ph / CI, comparable with IMP_yld and bal_yld'
   IMP_yld     'IMPACT YLDCTYX0 per harvested ha (AGG: area-weighted)'
   bal_yld     'balanced yield per harvested ha = bal_prod / bal_harv'
   yld_bal_AP  'bal_yld / AP_yld'
   yld_bal_IMP 'bal_yld / IMP_yld' /;
parameters
   ap_area_c(cty,JCROP,SYS), ap_prod_c(cty,JCROP,SYS), bal_area_c(cty,JCROP,SYS), bal_prod_c(cty,JCROP,SYS)
   imp_area_c(cty,JCROP,SYS), imp_prod_c(cty,JCROP,SYS), bal_phys_c(cty,JCROP,SYS), ap_drop_c(cty,JCROP,SYS) ;
ap_area_c(cty_run,JCROP,SYS)  = sum(pid$pid_cty(pid,cty_run), p_Area_pid(pid,JCROP,SYS));
ap_prod_c(cty_run,JCROP,SYS)  = sum(pid$pid_cty(pid,cty_run), p_Production_pid(pid,JCROP,SYS));
ap_drop_c(cty_run,JCROP,SYS)  = sum(pid$pid_cty(pid,cty_run), p_Area_ap_dropped(pid,JCROP,SYS));
bal_area_c(cty_run,JCROP,SYS) = sum(pid$pid_cty(pid,cty_run), p_Area_harv(pid,JCROP,SYS));
bal_phys_c(cty_run,JCROP,SYS) = sum(pid$pid_cty(pid,cty_run), p_Area_lu(pid,JCROP,SYS));
bal_prod_c(cty_run,JCROP,SYS) = sum(pid$pid_cty(pid,cty_run), p_Production_harv(pid,JCROP,SYS));
imp_area_c(cty_run,JCROP,SYS) = area_harv_cty(cty_run,JCROP,SYS,'%BASEYEAR%');
imp_prod_c(cty_run,JCROP,s_bal) = area_harv_cty(cty_run,JCROP,s_bal,'%BASEYEAR%') * yield_cty(cty_run,JCROP,s_bal,'%BASEYEAR%');
imp_prod_c(cty_run,JCROP,'AGG') = sum(s_bal, imp_prod_c(cty_run,JCROP,s_bal));

* the crop index is JCROP + ALL_CROPS, so it is declared on the universe
parameter crop_cmp(cty,*,SYS,item) 'crop-specific totals: AP vs IMPACT vs balanced (1000 ha, 1000 t, t/ha)';
crop_cmp(cty_run,JCROP,SYS,'AP_area')    = ap_area_c(cty_run,JCROP,SYS);
crop_cmp(cty_run,JCROP,SYS,'IMP_area')   = imp_area_c(cty_run,JCROP,SYS);
crop_cmp(cty_run,JCROP,SYS,'bal_harv')   = bal_area_c(cty_run,JCROP,SYS);
crop_cmp(cty_run,JCROP,SYS,'bal_phys')   = bal_phys_c(cty_run,JCROP,SYS);
crop_cmp(cty_run,JCROP,SYS,'AP_dropped') = ap_drop_c(cty_run,JCROP,SYS);
crop_cmp(cty_run,JCROP,SYS,'AP_prod')    = ap_prod_c(cty_run,JCROP,SYS);
crop_cmp(cty_run,JCROP,SYS,'IMP_prod')   = imp_prod_c(cty_run,JCROP,SYS);
crop_cmp(cty_run,JCROP,SYS,'bal_prod')   = bal_prod_c(cty_run,JCROP,SYS);
set item_sum(item) 'additive columns, summed into the ALL_CROPS row' / AP_area, bal_phys, IMP_area, bal_harv, AP_dropped, AP_prod, IMP_prod, bal_prod /;
crop_cmp(cty_run,'ALL_CROPS',SYS,item_sum) = sum(JCROP, crop_cmp(cty_run,JCROP,SYS,item_sum));

set rowj 'rows of crop_cmp' / ALL_CROPS /;
rowj(JCROP) = yes;
crop_cmp(cty_run,rowj,SYS,'bal_to_AP')$(crop_cmp(cty_run,rowj,SYS,'AP_area') > 0)
   = crop_cmp(cty_run,rowj,SYS,'bal_phys') / crop_cmp(cty_run,rowj,SYS,'AP_area');
crop_cmp(cty_run,rowj,SYS,'AP_yld_ph')$(crop_cmp(cty_run,rowj,SYS,'AP_area') > 0)
   = crop_cmp(cty_run,rowj,SYS,'AP_prod') / crop_cmp(cty_run,rowj,SYS,'AP_area');
crop_cmp(cty_run,rowj,SYS,'AP_yld')$crop_intens(cty_run,'%BASEYEAR%')
   = crop_cmp(cty_run,rowj,SYS,'AP_yld_ph') / crop_intens(cty_run,'%BASEYEAR%');
crop_cmp(cty_run,rowj,SYS,'IMP_yld')$(crop_cmp(cty_run,rowj,SYS,'IMP_area') > 0)
   = crop_cmp(cty_run,rowj,SYS,'IMP_prod') / crop_cmp(cty_run,rowj,SYS,'IMP_area');
crop_cmp(cty_run,rowj,SYS,'bal_yld')$(crop_cmp(cty_run,rowj,SYS,'bal_harv') > 0)
   = crop_cmp(cty_run,rowj,SYS,'bal_prod') / crop_cmp(cty_run,rowj,SYS,'bal_harv');
crop_cmp(cty_run,rowj,SYS,'yld_bal_AP')$(crop_cmp(cty_run,rowj,SYS,'AP_yld') > 0)
   = crop_cmp(cty_run,rowj,SYS,'bal_yld') / crop_cmp(cty_run,rowj,SYS,'AP_yld');
crop_cmp(cty_run,rowj,SYS,'yld_bal_IMP')$(crop_cmp(cty_run,rowj,SYS,'IMP_yld') > 0)
   = crop_cmp(cty_run,rowj,SYS,'bal_yld') / crop_cmp(cty_run,rowj,SYS,'IMP_yld');

* yields by crop-system, kept as a compact view for the summary below
set ysrc 'yield source' / AP, IMPACT, balanced, bal_to_AP, bal_to_IMP /;
parameter yld(cty,JCROP,SYS,ysrc) 'yield by crop and system, t per harvested ha (AP converted from per physical ha by CI), and ratios';
yld(cty_run,JCROP,SYS,'AP')         = crop_cmp(cty_run,JCROP,SYS,'AP_yld');
yld(cty_run,JCROP,SYS,'IMPACT')     = crop_cmp(cty_run,JCROP,SYS,'IMP_yld');
yld(cty_run,JCROP,SYS,'balanced')   = crop_cmp(cty_run,JCROP,SYS,'bal_yld');
yld(cty_run,JCROP,SYS,'bal_to_AP')  = crop_cmp(cty_run,JCROP,SYS,'yld_bal_AP');
yld(cty_run,JCROP,SYS,'bal_to_IMP') = crop_cmp(cty_run,JCROP,SYS,'yld_bal_IMP');

* country-level summary of how far the balanced yields sit from each source (area-weighted over crop-systems)
set ydev 'yield deviation summary' /
   n_cs_AP         'crop-systems (IR, RF) with both an AP and a balanced yield'
   wmad_bal_AP     'area-weighted mean |balanced/AP - 1| over those crop-systems (AP yield per harvested-equivalent ha)'
   n_cs_IMP        'crop-systems (IR, RF) with both an IMPACT and a balanced yield'
   wmad_bal_IMP    'area-weighted mean |balanced/IMPACT - 1| over those crop-systems'
   agg_AP          'AP aggregate yield, all crops AGG, per harvested-equivalent ha = prod / (physical area x CI) (t/ha)'
   agg_IMPACT      'IMPACT aggregate yield, all crops AGG (t/ha)'
   agg_balanced    'balanced aggregate yield, all crops AGG (t/ha)' /;
parameter yld_summary(cty,ydev) 'how close the balanced yields are to AP and to IMPACT';
yld_summary(cty_run,'n_cs_AP')  = sum((JCROP,s_bal)$(yld(cty_run,JCROP,s_bal,'bal_to_AP') > 0), 1);
yld_summary(cty_run,'n_cs_IMP') = sum((JCROP,s_bal)$(yld(cty_run,JCROP,s_bal,'bal_to_IMP') > 0), 1);
yld_summary(cty_run,'wmad_bal_AP')$sum((JCROP,s_bal)$(yld(cty_run,JCROP,s_bal,'bal_to_AP') > 0), bal_area_c(cty_run,JCROP,s_bal))
   = sum((JCROP,s_bal)$(yld(cty_run,JCROP,s_bal,'bal_to_AP') > 0), bal_area_c(cty_run,JCROP,s_bal) * abs(yld(cty_run,JCROP,s_bal,'bal_to_AP') - 1))
     / sum((JCROP,s_bal)$(yld(cty_run,JCROP,s_bal,'bal_to_AP') > 0), bal_area_c(cty_run,JCROP,s_bal));
yld_summary(cty_run,'wmad_bal_IMP')$sum((JCROP,s_bal)$(yld(cty_run,JCROP,s_bal,'bal_to_IMP') > 0), bal_area_c(cty_run,JCROP,s_bal))
   = sum((JCROP,s_bal)$(yld(cty_run,JCROP,s_bal,'bal_to_IMP') > 0), bal_area_c(cty_run,JCROP,s_bal) * abs(yld(cty_run,JCROP,s_bal,'bal_to_IMP') - 1))
     / sum((JCROP,s_bal)$(yld(cty_run,JCROP,s_bal,'bal_to_IMP') > 0), bal_area_c(cty_run,JCROP,s_bal));
yld_summary(cty_run,'agg_AP')       = crop_tot('s1_AP_on_pid_grid',cty_run,'AGG','yield');
yld_summary(cty_run,'agg_IMPACT')   = crop_tot('s1b_IMPACT_harv',cty_run,'AGG','yield');
yld_summary(cty_run,'agg_balanced') = crop_tot('s2_balanced_harv',cty_run,'AGG','yield');

* ================================================================ the two margin checks, cell by cell
* rows: for every pid in pid_run, balanced physical area summed over crops and IR+RF against lu_out crop
* diff is always BALANCED minus TARGET; rel_diff = diff / target. LUMEN outputs physical area only, IMPACT reports harvested.
set rchk 'columns of pid_check' /
   LUMEN_phys    'TARGET: LUMEN lu_out(pid,crop,BASEYEAR) (1000 ha, physical)'
   BAL_phys_sum  'BALANCED: sum over crops and IR+RF of p_Area_lu (1000 ha, physical)'
   diff          'BAL_phys_sum - LUMEN_phys (1000 ha)'
   rel_diff      '(BAL_phys_sum - LUMEN_phys) / LUMEN_phys' /;
parameter pid_check(pid,rchk) 'per-pid check: balanced PHYSICAL area vs LUMEN lu_out crop (physical) at BASEYEAR';
pid_check(pid_run,'LUMEN_phys')   = lu_out(pid_run,'crop','%BASEYEAR%');
pid_check(pid_run,'BAL_phys_sum') = sum(JCROP, p_Area_lu(pid_run,JCROP,'AGG'));
pid_check(pid_run,'diff')         = pid_check(pid_run,'BAL_phys_sum') - pid_check(pid_run,'LUMEN_phys');
pid_check(pid_run,'rel_diff')$pid_check(pid_run,'LUMEN_phys') = pid_check(pid_run,'diff') / pid_check(pid_run,'LUMEN_phys');

* columns: for every crop-system IMPACT has area for, balanced harvested area summed over pids against AREACTYX0
set cchk 'columns of cs_check' /
   IMPACT_harv   'TARGET: IMPACT AREACTYX0(j,cty,sys,BASEYEAR) (1000 ha, harvested)'
   BAL_harv_sum  'BALANCED: sum over pids of p_Area_harv (1000 ha, harvested = physical x IMPACT CROPINTENSX0)'
   diff          'BAL_harv_sum - IMPACT_harv (1000 ha)'
   rel_diff      '(BAL_harv_sum - IMPACT_harv) / IMPACT_harv' /;
parameter cs_check(cty,JCROP,SYS,cchk) 'per crop-system check: balanced HARVESTED area vs IMPACT AREACTYX0 (harvested) at BASEYEAR';
cs_check(cty_run,JCROP,s_bal,'IMPACT_harv')$(imp_area_c(cty_run,JCROP,s_bal) > 0 or bal_area_c(cty_run,JCROP,s_bal) > 0) = imp_area_c(cty_run,JCROP,s_bal);
cs_check(cty_run,JCROP,s_bal,'BAL_harv_sum')$(imp_area_c(cty_run,JCROP,s_bal) > 0 or bal_area_c(cty_run,JCROP,s_bal) > 0) = bal_area_c(cty_run,JCROP,s_bal);
cs_check(cty_run,JCROP,s_bal,'diff')     = cs_check(cty_run,JCROP,s_bal,'BAL_harv_sum') - cs_check(cty_run,JCROP,s_bal,'IMPACT_harv');
cs_check(cty_run,JCROP,s_bal,'rel_diff')$cs_check(cty_run,JCROP,s_bal,'IMPACT_harv') = cs_check(cty_run,JCROP,s_bal,'diff') / cs_check(cty_run,JCROP,s_bal,'IMPACT_harv');

set mchk 'margin check summary' /
   n_pid          'pids in pid_run checked'
   n_pid_off      'pids with |rel_diff| > 1e-9'
   pid_max_abs    'max |BAL_phys_sum - LUMEN_phys| over pids (1000 ha)'
   pid_max_rel    'max |rel_diff| over pids'
   n_cs           'crop-systems (IR, RF) with IMPACT or balanced area checked'
   n_cs_off       'crop-systems with |rel_diff| > 1e-9'
   cs_max_abs     'max |BAL_harv_sum - IMPACT_harv| over crop-systems (1000 ha)'
   cs_max_rel     'max |rel_diff| over crop-systems' /;
parameter margin_check(cty,mchk) 'worst case of the two margin checks: pids (balanced physical vs LUMEN physical), crop-systems (balanced harvested vs IMPACT harvested)';
margin_check(cty_run,'n_pid')       = sum(pid_run$pid_cty(pid_run,cty_run), 1);
margin_check(cty_run,'n_pid_off')   = sum(pid_run$(pid_cty(pid_run,cty_run) and abs(pid_check(pid_run,'rel_diff')) > 1e-9), 1);
margin_check(cty_run,'pid_max_abs') = smax(pid_run$pid_cty(pid_run,cty_run), abs(pid_check(pid_run,'diff')));
margin_check(cty_run,'pid_max_rel') = smax(pid_run$pid_cty(pid_run,cty_run), abs(pid_check(pid_run,'rel_diff')));
margin_check(cty_run,'n_cs')        = sum((JCROP,s_bal)$(cs_check(cty_run,JCROP,s_bal,'IMPACT_harv') > 0 or cs_check(cty_run,JCROP,s_bal,'BAL_harv_sum') > 0), 1);
margin_check(cty_run,'n_cs_off')    = sum((JCROP,s_bal)$(abs(cs_check(cty_run,JCROP,s_bal,'rel_diff')) > 1e-9
                                          or (cs_check(cty_run,JCROP,s_bal,'IMPACT_harv') = 0 and cs_check(cty_run,JCROP,s_bal,'BAL_harv_sum') > 0)), 1);
margin_check(cty_run,'cs_max_abs')  = smax((JCROP,s_bal), abs(cs_check(cty_run,JCROP,s_bal,'diff')));
margin_check(cty_run,'cs_max_rel')  = smax((JCROP,s_bal), abs(cs_check(cty_run,JCROP,s_bal,'rel_diff')));
* a zero count would be dropped from the display and the GDX; EPS keeps the record so 'none off' is visible
margin_check(cty_run,'n_pid_off')$(margin_check(cty_run,'n_pid_off') = 0) = EPS;
margin_check(cty_run,'n_cs_off')$(margin_check(cty_run,'n_cs_off') = 0)   = EPS;

* ================================================================ land totals by pool
set lsrc 'source of the land total' /
   lu_out     'LUMEN: sum over pid_run of lu_out at BASEYEAR'
   lu_cty     'LUMEN: lu_cty from solution_lu at BASEYEAR'
   IMPACT_ctl 'IMPACT control: impact_total from solution_lu at BASEYEAR' /;

* the pool index is fland + total, so it is declared on the universe
parameter land_tot(cty,*,lsrc) 'land by pool and country at BASEYEAR (1000 ha)';
land_tot(cty_run,fland,'lu_out')     = sum(pid_run$pid_cty(pid_run,cty_run), lu_out(pid_run,fland,'%BASEYEAR%'));
land_tot(cty_run,fland,'lu_cty')     = lu_cty(cty_run,fland,'%BASEYEAR%');
land_tot(cty_run,fland,'IMPACT_ctl') = impact_total(cty_run,fland,'%BASEYEAR%');
land_tot(cty_run,'total',lsrc)       = sum(fland, land_tot(cty_run,fland,lsrc));

parameter land_by_year(cty,*,yrs) 'LUMEN lu_out by pool and year over pid_run (1000 ha)';
land_by_year(cty_run,fland,yrs)   = sum(pid_run$pid_cty(pid_run,cty_run), lu_out(pid_run,fland,yrs));
land_by_year(cty_run,'total',yrs) = sum(fland, land_by_year(cty_run,fland,yrs));

* ================================================================ display
scalar base_year 'LUMEN year used as the anchor' / %BASEYEAR% /;
parameter cropping_intensity(cty) 'IMPACT CROPINTENSX0 at BASEYEAR';
cropping_intensity(cty_run) = crop_intens(cty_run,'%BASEYEAR%');

option decimals = 3;
option crop_tot:3:2:2, crop_cmp:3:3:1, yld_summary:3:1:1, land_tot:3:2:1, land_by_year:3:2:1, margin_check:8:0:1;
display base_year, cropping_intensity, stage, crop_tot, yld_summary, item, crop_cmp, land_tot, land_by_year, mchk, margin_check;

* ================================================================ GDX with the same tables
execute_unload '%OUT%',
   base_year, cty_run, cropping_intensity,
   stage, metric, crop_tot,
   item, crop_cmp, ysrc, yld, ydev, yld_summary,
   rchk, pid_check, cchk, cs_check, mchk, margin_check,
   lsrc, land_tot, land_by_year;
