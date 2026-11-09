$title Step 5 - one GDX for the Crop Allocation Model: balanced areas, yields, LUMEN cropland path, IMPACT targets, crosswalk
$onEolCom

* Called by src/run.py (or by hand) with
*   gams src/step5_handoff.gms pf=output/secondary/step5_handoff.pf
* where the parameter file holds
*   --LU=<solution_lu.gdx> --TARGETS=<cty_impact_targets.gdx> --BAL=<cty_crop_in_pid_coords_balanced.gdx>
*   --OUT=<cty_for_CropAllocation.gdx> --BASEYEAR=<yyyy>
*
* Everything the Crop Allocation Model needs from this pipeline, in one file, with the spatial unit
* being the LUMEN 0.25-deg pixel (set KEY; GAMS is case-insensitive so it cannot be called PID next to LUMEN's pid). Names follow the Crop Allocation Model where a counterpart
* exists (p_Area, p_Production, p_Yield, AREACTYX0, YLDCTYX0, PIXEL_TO_DIM-style crosswalk); the
* explanatory text of every symbol states its unit and basis.
*
* Area bases, so nothing is mixed up downstream:
*   harvested  IMPACT AREACTYX0, p_Area and p_Area_harv here                                (1000 ha)
*   physical   the AP file p_Area (SPAM physical area mapped to IMPACT crops), LUMEN lu_out crop,
*              LANDX0, p_Area_AP, p_Area_phys and p_Cropland here                           (1000 ha)
*   p_Area_harv = p_Area_phys x CROPINTENSX0(cty, base year), one scalar per country.
* Nothing in this pipeline reads the file; it is a hand-off.

$if not set LU       $abort --LU=<solution_lu.gdx> is required
$if not set TARGETS  $abort --TARGETS=<cty_impact_targets.gdx> is required
$if not set BAL      $abort --BAL=<balanced.gdx> is required
$if not set OUT      $abort --OUT=<cty_for_CropAllocation.gdx> is required
$if not set BASEYEAR $abort --BASEYEAR=<yyyy> is required

* ---------------- balanced result (step 2) ----------------
sets
   pid       'LUMEN 0.25-deg pixel IDs'
   cty       'countries'
   JCROP     'crops (IMPACT j-codes)'
   SYS       'production system'
   coord     'coordinates'
   PIXEL_S   'AP 5-arcmin pixel keys in the AP country file'
   PIXEL_UNMAPPED(PIXEL_S)        'AP pixels with no pid in the LUMEN land mask'
   PIXEL_TO_PID_AP(PIXEL_S,pid)   'AP pixels -> LUMEN pid'
   pid_run(pid), cty_run(cty), pid_cty(pid,cty), pid_balanced(pid), pid_outside_run(pid) ;
parameters
   p_Area_pid(pid,JCROP,SYS), p_Production_pid(pid,JCROP,SYS)
   p_Area_lu(pid,JCROP,SYS), bal_harv(pid,JCROP,SYS), p_Production_harv(pid,JCROP,SYS), p_Yield_used(pid,JCROP,SYS)
   yield_source(pid,JCROP,SYS), seed_source(pid,JCROP,SYS), ras_row(pid), ras_col(cty,JCROP,SYS)
   bal_dropped(pid,JCROP,SYS), p_Production_ap_dropped(pid,JCROP,SYS), n_ap_pix(pid), ci(cty) ;
$gdxIn "%BAL%"
$load pid cty JCROP SYS coord PIXEL_S PIXEL_UNMAPPED PIXEL_TO_PID_AP pid_run cty_run pid_cty pid_balanced pid_outside_run
$loadDC p_Area_pid p_Production_pid p_Area_lu bal_harv=p_Area_harv p_Production_harv p_Yield_used
$loadDC yield_source seed_source ras_row ras_col bal_dropped=p_Area_ap_dropped p_Production_ap_dropped n_ap_pix ci
$gdxIn

* ---------------- LUMEN: land use path and coordinates ----------------
sets fland 'land pools', yrs 'years';
parameters lu_out(pid,fland,yrs), pid_coords(pid,coord);
$gdxIn "%LU%"
$load fland yrs
$loadDC lu_out pid_coords
$gdxIn
abort$(not sum(yrs$sameas(yrs,'%BASEYEAR%'), 1)) 'BASEYEAR is not a year in solution_lu yrs', yrs;

* ---------------- IMPACT targets (step 1b) ----------------
parameters area_harv_cty(cty,JCROP,SYS,yrs), yield_cty(cty,JCROP,SYS,yrs), crop_intens(cty,yrs), landx0_crop(cty,yrs);
$gdxIn "%TARGETS%"
$loadDC area_harv_cty yield_cty crop_intens landx0_crop
$gdxIn

* ================================================================ the hand-off symbols
scalar base_year 'LUMEN year the balance is anchored to; all pixel-level symbols refer to this year' / %BASEYEAR% /;

sets
   RUNCTY(cty)             'IMPACT country code(s) covered by this file (the Crop Allocation Model name for the selected countries)'
   KEY(pid)             'LUMEN 0.25-deg pixels of the country: the spatial units, all of LUMEN pid_run (the Crop Allocation Model name for the selected layer elements)'
   CTY_TO_PID(cty,pid)  'country -> LUMEN pixel, as LUMEN assigns them'
   PIXEL(PIXEL_S)       'AP 5-arcmin pixel keys of the AP country file (same keys as PIXEL_TO_DIM there)'
   PIXEL_TO_PID(PIXEL_S,pid) 'AP 5-arcmin pixel -> the LUMEN pixel that contains it (9 AP pixels per LUMEN pixel)'
   PIXEL_NO_PID(PIXEL_S) 'AP pixels whose cell is outside the LUMEN land mask: no LUMEN pixel, their data are not in this file'
   KEY_OTHER_CTY(pid)     'LUMEN pixels carrying AP area that LUMEN assigns to another country: AP data there were dropped' ;
RUNCTY(cty_run) = yes;
KEY(pid_run) = yes;
CTY_TO_PID(cty_run,pid_run)$pid_cty(pid_run,cty_run) = yes;
PIXEL(PIXEL_S) = yes;
PIXEL_TO_PID(PIXEL_S,pid) = PIXEL_TO_PID_AP(PIXEL_S,pid);
PIXEL_NO_PID(PIXEL_UNMAPPED) = yes;
KEY_OTHER_CTY(pid_outside_run) = yes;

parameters
   p_Coords(pid,coord)         'cell-centre coordinates of the LUMEN pixel (deg; x = lon, y = lat)'
   p_Area(pid,JCROP,SYS)       'HARVESTED crop area at base_year, balanced (1000 ha). Sums over KEY to AREACTYX0(j,cty,sys). Same basis as IMPACT; NOT the basis of the AP file, which is physical'
   p_Area_harv(pid,JCROP,SYS)  'identical to p_Area; the explicit name (1000 ha, harvested)'
   p_Area_phys(pid,JCROP,SYS)  'PHYSICAL cropland at base_year, balanced (1000 ha). Sums over crops and IR+RF to LUMEN lu_out(pid,crop,base_year). = p_Area_harv / CROPINTENSX0'
   p_Production(pid,JCROP,SYS) 'crop production at base_year, balanced (1000 t): p_Area_phys x AP yield per physical ha where AP has data, else p_Area_harv x YLDCTYX0; always = p_Area_harv x p_Yield'
   p_Yield(pid,JCROP,SYS)      'yield applied, t per HARVESTED ha = p_Production / p_Area_harv. AP yields are per physical ha in the AP file and appear here divided by CROPINTENSX0. See p_YieldSource'
   p_YieldSource(pid,JCROP,SYS) '1 = AP cell yield (AP production / AP PHYSICAL area on this pixel, applied to p_Area_phys), 2 = AP country yield for the crop-system (same basis), 3 = IMPACT YLDCTYX0 (per harvested ha, applied to p_Area_harv)'
   p_SeedSource(pid,JCROP,SYS) '1 = AP area on this pixel and crop-system, 2 = crop-system absent from AP, seeded with the AP system footprint, 3 = pixel with no usable AP mix, seeded with the national IMPACT mix'
   p_RasRow(pid)               'RAS pixel factor: product of all row corrections (LUMEN cropland / pixel sum) over the passes. On AP cells p_Area_phys = p_Area_AP x p_RasRow x p_RasCol. Far from 1: AP cropland on the pixel far from LUMEN'
   p_RasCol(cty,JCROP,SYS)     'RAS crop-system factor: product of all column corrections (IMPACT target / national sum) over the passes. Far from 1: AP and IMPACT disagree on the national total of this crop-system'
   p_Area_AP(pid,JCROP,SYS)    'the AP file p_Area summed onto the LUMEN pixel, untouched (1000 ha, PHYSICAL: SPAM physical area mapped to IMPACT crops) - compare with p_Area_phys'
   p_Production_AP(pid,JCROP,SYS) 'the AP file p_Production summed onto the LUMEN pixel, untouched (1000 t)'
   p_Area_AP_dropped(pid,JCROP,SYS) 'AP area not used: pixel assigned to another country by LUMEN, lu_out crop = 0, or no IMPACT area for the crop-system (1000 ha)'
   p_nAPpix(pid)               'AP 5-arcmin pixels feeding this LUMEN pixel (9 = fully covered)'
   p_Cropland(pid,yrs)         'LUMEN physical cropland per pixel by year, lu_out(pid,crop,yrs) (1000 ha): the land constraint path. At base_year it equals sum of p_Area_phys'
   p_Land(pid,fland,yrs)       'LUMEN land use per pixel by pool and year, lu_out (1000 ha)'
   AREACTYX0(JCROP,cty,SYS,yrs) 'IMPACT harvested area (1000 ha); IMPACT fctr air -> IR, arf -> RF, AGG = IR + RF'
   YLDCTYX0(JCROP,cty,SYS,yrs)  'IMPACT yield (t per harvested ha); AGG = area-weighted'
   CROPINTENSX0(cty,yrs)        'IMPACT cropping intensity = harvested / physical'
   LANDX0(cty,yrs)              'IMPACT LANDX0 crop: physical cropland (1000 ha) = sum over pid of p_Cropland' ;

p_Coords(KEY,coord)           = pid_coords(KEY,coord);
p_Area(KEY,JCROP,SYS)         = bal_harv(KEY,JCROP,SYS);
p_Area_harv(KEY,JCROP,SYS)    = bal_harv(KEY,JCROP,SYS);
p_Area_phys(KEY,JCROP,SYS)    = p_Area_lu(KEY,JCROP,SYS);
p_Production(KEY,JCROP,SYS)   = p_Production_harv(KEY,JCROP,SYS);
p_Yield(KEY,JCROP,SYS)        = p_Yield_used(KEY,JCROP,SYS);
p_YieldSource(KEY,JCROP,SYS)  = yield_source(KEY,JCROP,SYS);
p_SeedSource(KEY,JCROP,SYS)   = seed_source(KEY,JCROP,SYS);
p_RasRow(KEY)                 = ras_row(KEY);
p_RasCol(RUNCTY,JCROP,SYS)       = ras_col(RUNCTY,JCROP,SYS);
p_Area_AP(pid,JCROP,SYS)$(KEY(pid) or KEY_OTHER_CTY(pid))        = p_Area_pid(pid,JCROP,SYS);
p_Production_AP(pid,JCROP,SYS)$(KEY(pid) or KEY_OTHER_CTY(pid))  = p_Production_pid(pid,JCROP,SYS);
p_Area_AP_dropped(pid,JCROP,SYS)                               = bal_dropped(pid,JCROP,SYS);
p_nAPpix(pid)$(KEY(pid) or KEY_OTHER_CTY(pid))                   = n_ap_pix(pid);
p_Cropland(KEY,yrs)           = lu_out(KEY,'crop',yrs);
p_Land(KEY,fland,yrs)         = lu_out(KEY,fland,yrs);
AREACTYX0(JCROP,RUNCTY,SYS,yrs)  = area_harv_cty(RUNCTY,JCROP,SYS,yrs);
YLDCTYX0(JCROP,RUNCTY,SYS,yrs)   = yield_cty(RUNCTY,JCROP,SYS,yrs);
CROPINTENSX0(RUNCTY,yrs)         = crop_intens(RUNCTY,yrs);
LANDX0(RUNCTY,yrs)               = landx0_crop(RUNCTY,yrs);

* ================================================================ guards: the file must carry the two identities
scalars chk_pid 'max relative gap: sum of p_Area_phys per pixel vs p_Cropland at base_year',
        chk_cs  'max relative gap: sum of p_Area per crop-system vs AREACTYX0 at base_year',
        chk_ci  'max relative gap: p_Area vs p_Area_phys x CROPINTENSX0';
chk_pid = smax(KEY$(p_Cropland(KEY,'%BASEYEAR%') > 0),
              abs(sum(JCROP, p_Area_phys(KEY,JCROP,'AGG')) - p_Cropland(KEY,'%BASEYEAR%')) / p_Cropland(KEY,'%BASEYEAR%'));
chk_cs  = smax((RUNCTY,JCROP,SYS)$(AREACTYX0(JCROP,RUNCTY,SYS,'%BASEYEAR%') > 0 and not sameas(SYS,'AGG')),
              abs(sum(KEY$CTY_TO_PID(RUNCTY,KEY), p_Area(KEY,JCROP,SYS)) - AREACTYX0(JCROP,RUNCTY,SYS,'%BASEYEAR%')) / AREACTYX0(JCROP,RUNCTY,SYS,'%BASEYEAR%'));
chk_ci  = smax((KEY,JCROP,SYS)$(p_Area_phys(KEY,JCROP,SYS) > 0),
              abs(p_Area(KEY,JCROP,SYS) - p_Area_phys(KEY,JCROP,SYS) * sum(RUNCTY$CTY_TO_PID(RUNCTY,KEY), CROPINTENSX0(RUNCTY,'%BASEYEAR%'))) / p_Area(KEY,JCROP,SYS));
display base_year, chk_pid, chk_cs, chk_ci;
abort$(chk_pid > 1e-12) 'hand-off file: pixel sums of p_Area_phys do not reproduce p_Cropland', chk_pid;
abort$(chk_cs  > 1e-9)  'hand-off file: crop-system sums of p_Area do not reproduce AREACTYX0', chk_cs;
abort$(chk_ci  > 1e-12) 'hand-off file: p_Area is not p_Area_phys x CROPINTENSX0', chk_ci;

* ================================================================ the same two identities as tables, so they can be inspected in the GDX
* Column names say where each number comes from and on which basis it is. LUMEN outputs PHYSICAL area
* only; IMPACT AREACTYX0 is HARVESTED area; every harvested figure derived here is physical x IMPACT's
* CROPINTENSX0 (one national scalar), and every physical figure derived from IMPACT is harvested / CROPINTENSX0.
* diff is always BALANCED minus TARGET; rel_diff is diff divided by the target.
set pxcol 'columns of Test_PixelSum' /
   LUMEN_phys        'TARGET: LUMEN lu_out crop on the pixel at base_year (1000 ha, physical - LUMEN outputs physical only)'
   BAL_phys_sum      'BALANCED: sum over crops and IR+RF of p_Area_phys (1000 ha, physical)'
   BAL_harv_sum      'derived: BAL_phys_sum x IMPACT CROPINTENSX0 = sum over crops of p_Area (1000 ha, harvested-equivalent); not tested'
   AP_phys_sum       'reference: sum over crops of p_Area_AP on the pixel (1000 ha, physical - SPAM physical area in the AP file, before balancing); not a target'
   BAL_to_AP         'reference: BAL_phys_sum / AP_phys_sum = how much the pixel total moved from AP to LUMEN (the RAS row factor net of column factors)'
   diff              'BAL_phys_sum - LUMEN_phys (1000 ha)'
   rel_diff          '(BAL_phys_sum - LUMEN_phys) / LUMEN_phys' /;
parameter Test_PixelSum(pid,pxcol) 'TEST per pixel: balanced PHYSICAL area summed over crops == LUMEN physical cropland (p_Cropland) at base_year; AP original for reference';
Test_PixelSum(KEY,'LUMEN_phys')   = p_Cropland(KEY,'%BASEYEAR%');
Test_PixelSum(KEY,'BAL_phys_sum') = sum(JCROP, p_Area_phys(KEY,JCROP,'AGG'));
Test_PixelSum(KEY,'BAL_harv_sum') = sum(JCROP, p_Area(KEY,JCROP,'AGG'));
Test_PixelSum(KEY,'AP_phys_sum')  = sum(JCROP, p_Area_AP(KEY,JCROP,'AGG'));
Test_PixelSum(KEY,'BAL_to_AP')$Test_PixelSum(KEY,'AP_phys_sum') = Test_PixelSum(KEY,'BAL_phys_sum') / Test_PixelSum(KEY,'AP_phys_sum');
Test_PixelSum(KEY,'diff')         = Test_PixelSum(KEY,'BAL_phys_sum') - Test_PixelSum(KEY,'LUMEN_phys');
Test_PixelSum(KEY,'rel_diff')$Test_PixelSum(KEY,'LUMEN_phys') = Test_PixelSum(KEY,'diff') / Test_PixelSum(KEY,'LUMEN_phys');

set crcol 'columns of Test_CropSum' /
   IMPACT_harv       'TARGET: IMPACT AREACTYX0 for the country at base_year (1000 ha, harvested - IMPACT reports harvested area)'
   BAL_harv_sum      'BALANCED: sum over the KEY pixels of p_Area (1000 ha, harvested = physical x IMPACT CROPINTENSX0)'
   BAL_phys_sum      'derived: sum over the KEY pixels of p_Area_phys (1000 ha, physical) = BAL_harv_sum / CROPINTENSX0; not tested'
   IMPACT_phys       'derived: IMPACT_harv / CROPINTENSX0 (1000 ha, physical-equivalent); equals BAL_phys_sum; not tested'
   AP_phys_sum       'reference: sum over the KEY pixels of p_Area_AP (1000 ha, physical - SPAM physical area in the AP file); not a target'
   diff              'BAL_harv_sum - IMPACT_harv (1000 ha)'
   rel_diff          '(BAL_harv_sum - IMPACT_harv) / IMPACT_harv' /;
parameter Test_CropSum(cty,JCROP,SYS,crcol) 'TEST per crop and system: balanced HARVESTED area summed over the pixels of the country == IMPACT AREACTYX0 (harvested) at base_year';
Test_CropSum(RUNCTY,JCROP,SYS,'IMPACT_harv')  = AREACTYX0(JCROP,RUNCTY,SYS,'%BASEYEAR%');
Test_CropSum(RUNCTY,JCROP,SYS,'BAL_harv_sum') = sum(KEY$CTY_TO_PID(RUNCTY,KEY), p_Area(KEY,JCROP,SYS));
Test_CropSum(RUNCTY,JCROP,SYS,'BAL_phys_sum') = sum(KEY$CTY_TO_PID(RUNCTY,KEY), p_Area_phys(KEY,JCROP,SYS));
Test_CropSum(RUNCTY,JCROP,SYS,'IMPACT_phys')$CROPINTENSX0(RUNCTY,'%BASEYEAR%')
   = Test_CropSum(RUNCTY,JCROP,SYS,'IMPACT_harv') / CROPINTENSX0(RUNCTY,'%BASEYEAR%');
Test_CropSum(RUNCTY,JCROP,SYS,'AP_phys_sum')  = sum(KEY$CTY_TO_PID(RUNCTY,KEY), p_Area_AP(KEY,JCROP,SYS));
Test_CropSum(RUNCTY,JCROP,SYS,'diff')         = Test_CropSum(RUNCTY,JCROP,SYS,'BAL_harv_sum') - Test_CropSum(RUNCTY,JCROP,SYS,'IMPACT_harv');
Test_CropSum(RUNCTY,JCROP,SYS,'rel_diff')$Test_CropSum(RUNCTY,JCROP,SYS,'IMPACT_harv')
   = Test_CropSum(RUNCTY,JCROP,SYS,'diff') / Test_CropSum(RUNCTY,JCROP,SYS,'IMPACT_harv');

set tcol 'rows of Test_Summary' /
   n_pixels       'pixels tested (all of KEY)'
   pix_max_abs    'largest |BAL_phys_sum - LUMEN_phys| over pixels (1000 ha)'
   pix_max_rel    'largest |rel_diff| over pixels'
   n_cropsys      'crop-systems (IR, RF) with IMPACT or balanced area tested'
   crop_max_abs   'largest |BAL_harv_sum - IMPACT_harv| over crop-systems (1000 ha)'
   crop_max_rel   'largest |rel_diff| over crop-systems' /;
parameter Test_Summary(cty,tcol) 'worst case of the two tests: pixels (balanced physical vs LUMEN physical) and crop-systems (balanced harvested vs IMPACT harvested)';
Test_Summary(RUNCTY,'n_pixels')     = sum(KEY$CTY_TO_PID(RUNCTY,KEY), 1);
Test_Summary(RUNCTY,'pix_max_abs')  = smax(KEY$CTY_TO_PID(RUNCTY,KEY), abs(Test_PixelSum(KEY,'diff')));
Test_Summary(RUNCTY,'pix_max_rel')  = smax(KEY$CTY_TO_PID(RUNCTY,KEY), abs(Test_PixelSum(KEY,'rel_diff')));
Test_Summary(RUNCTY,'n_cropsys')    = sum((JCROP,SYS)$(not sameas(SYS,'AGG') and (Test_CropSum(RUNCTY,JCROP,SYS,'IMPACT_harv') > 0 or Test_CropSum(RUNCTY,JCROP,SYS,'BAL_harv_sum') > 0)), 1);
Test_Summary(RUNCTY,'crop_max_abs') = smax((JCROP,SYS)$(not sameas(SYS,'AGG')), abs(Test_CropSum(RUNCTY,JCROP,SYS,'diff')));
Test_Summary(RUNCTY,'crop_max_rel') = smax((JCROP,SYS)$(not sameas(SYS,'AGG')), abs(Test_CropSum(RUNCTY,JCROP,SYS,'rel_diff')));
option Test_Summary:8:0:1;
display Test_Summary;

execute_unload '%OUT%',
   base_year,
   RUNCTY, KEY, CTY_TO_PID, JCROP, SYS, yrs, fland, coord,
   PIXEL, PIXEL_TO_PID, PIXEL_NO_PID, KEY_OTHER_CTY,
   p_Coords,
   p_Area, p_Area_harv, p_Area_phys, p_Production, p_Yield, p_YieldSource, p_SeedSource, p_RasRow, p_RasCol,
   p_Area_AP, p_Production_AP, p_Area_AP_dropped, p_nAPpix,
   p_Cropland, p_Land,
   AREACTYX0, YLDCTYX0, CROPINTENSX0, LANDX0,
   pxcol, Test_PixelSum, crcol, Test_CropSum, tcol, Test_Summary;
