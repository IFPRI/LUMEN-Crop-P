"""Step 1b - pull the IMPACT country targets the balance needs out of an IMPACT scenario GDX.

The IMPACT scenario file is large (200+ MB); only a few symbols are read, restricted to the
countries in LUMEN's cty_run, and written to a small GDX that step 2 (GAMS) loads:

  AREACTYX0(J,CTY,FCTR,YRS)   harvested area by crop and system (1000 ha)  -> area_harv_cty(cty,JCROP,SYS,yrs)
  CROPINTENSX0(CTY,YRS)       cropping intensity = harvested / physical     -> crop_intens(cty,yrs)
  LANDX0(CTY,fland,YRS)       physical land pools, 'crop' used              -> landx0_crop(cty,yrs)
  YLDCTYX0(J,CTY,FCTR,YRS)    yield (t/ha), fallback where AP has no yield  -> yield_cty(cty,JCROP,SYS,yrs)

IMPACT systems air/arf are LUMEN-Crop systems IR/RF; AGG is their sum.

The identity that ties LUMEN to IMPACT is
    lu_out country crop total  ==  LANDX0(cty,'crop',yr)  ==  sum_j AREACTYX0(j,cty,.,yr) / CROPINTENSX0(cty,yr)
It is logged here for every LUMEN year and enforced in step 2 for the base year.
"""
import numpy as np
import pandas as pd
import gams.transfer as gt

from gdxio import PipelineError, new_gdx, records

FCTR_TO_SYS = {"air": "IR", "arf": "RF"}
AGG = "AGG"


def extract(impact_path, cty_run, yrs, gamsdir, log):
    """Read the symbols for cty_run. Returns dict of DataFrames + the IMPACT crop order."""
    if not cty_run:
        raise PipelineError("solution_lu has no cty_run; the IMPACT targets need a country code")
    c = gt.Container(system_directory=str(gamsdir))
    c.read(str(impact_path), symbols=["AREACTYX0", "CROPINTENSX0", "LANDX0", "YLDCTYX0", "CROPINTENS"])
    have = set(c.listSymbols())
    for s in ["AREACTYX0", "YLDCTYX0"]:
        if s not in have:
            raise PipelineError(f"IMPACT file has no {s}: {impact_path}")
    if "CROPINTENSX0" not in have and "CROPINTENS" not in have:
        raise PipelineError(f"IMPACT file has neither CROPINTENSX0 nor CROPINTENS: {impact_path}")

    cty = set(cty_run)
    yrs = [str(y) for y in yrs]

    area = records(c["AREACTYX0"], ["j", "cty", "fctr", "yrs", "value"])
    jorder = list(c["AREACTYX0"].records.iloc[:, 0].cat.categories)
    area = area[area.cty.isin(cty) & area.yrs.isin(yrs)].copy()
    if area.empty:
        raise PipelineError(f"AREACTYX0 has no records for {sorted(cty)} in years {yrs[0]}-{yrs[-1]}")
    bad = area[~area.fctr.isin(FCTR_TO_SYS) & (area.value != 0)]
    if not bad.empty:
        raise PipelineError(f"AREACTYX0 has area on FCTR other than air/arf: {sorted(bad.fctr.unique())}")
    area = area[area.fctr.isin(FCTR_TO_SYS)]
    area["sys"] = area.fctr.map(FCTR_TO_SYS)
    area = area.groupby(["cty", "j", "sys", "yrs"], as_index=False)["value"].sum()
    agg = area.groupby(["cty", "j", "yrs"], as_index=False)["value"].sum().assign(sys=AGG)
    area = pd.concat([area, agg[area.columns]], ignore_index=True)

    yld = records(c["YLDCTYX0"], ["j", "cty", "fctr", "yrs", "value"])
    yld = yld[yld.cty.isin(cty) & yld.yrs.isin(yrs) & yld.fctr.isin(FCTR_TO_SYS)].copy()
    yld["sys"] = yld.fctr.map(FCTR_TO_SYS)
    yld = yld[["cty", "j", "sys", "yrs", "value"]]

    if "CROPINTENSX0" in have:
        ci = records(c["CROPINTENSX0"], ["cty", "yrs", "value"])
        ci = ci[ci.cty.isin(cty) & ci.yrs.isin(yrs)]
        ci_src = "CROPINTENSX0(cty,yrs)"
    else:
        ci0 = records(c["CROPINTENS"], ["cty", "value"])
        ci0 = ci0[ci0.cty.isin(cty)]
        ci = ci0.merge(pd.DataFrame({"yrs": yrs}), how="cross")[["cty", "yrs", "value"]]
        ci_src = "CROPINTENS(cty), constant over years"
    missing = [(k, y) for k in sorted(cty) for y in yrs if not ((ci.cty == k) & (ci.yrs == y)).any()]
    if missing:
        raise PipelineError(f"cropping intensity missing for {missing[:5]}{'...' if len(missing) > 5 else ''}")
    if (ci.value <= 0).any():
        raise PipelineError("cropping intensity <= 0 for " + str(ci[ci.value <= 0].head().to_dict("records")))

    land = pd.DataFrame(columns=["cty", "yrs", "value"])
    if "LANDX0" in have:
        land = records(c["LANDX0"], ["cty", "fland", "yrs", "value"])
        land = land[land.cty.isin(cty) & land.yrs.isin(yrs) & (land.fland == "crop")][["cty", "yrs", "value"]]

    log(f"IMPACT : {impact_path.name}: AREACTYX0 {len(area[area.sys != AGG]):,} records for {sorted(cty)}, "
        f"{area.j.nunique()} crops, systems air/arf -> IR/RF; cropping intensity from {ci_src}"
        + ("; LANDX0 crop present" if len(land) else "; LANDX0 absent (physical-cropland cross-check skipped)"))
    return dict(area=area, yld=yld, ci=ci, land=land, jorder=jorder)


def check_country_totals(tg, lu_crop_cty, log):
    """lu_crop_cty: DataFrame (cty, yrs, value) = LUMEN pixel sums of lu_out(.,'crop',yrs) over pid_run.
    Logs, per country, the worst relative gap over all years between LUMEN and the two IMPACT
    expressions of physical cropland. Returns the merged table (one row per cty, yr)."""
    harv = tg["area"][tg["area"].sys == AGG].groupby(["cty", "yrs"], as_index=False)["value"].sum() \
        .rename(columns={"value": "impact_harv"})
    t = lu_crop_cty.rename(columns={"value": "lumen_crop"}).merge(harv, on=["cty", "yrs"], how="left") \
        .merge(tg["ci"].rename(columns={"value": "crop_intens"}), on=["cty", "yrs"], how="left")
    t["impact_phys"] = t.impact_harv / t.crop_intens
    if len(tg["land"]):
        t = t.merge(tg["land"].rename(columns={"value": "landx0_crop"}), on=["cty", "yrs"], how="left")
    else:
        t["landx0_crop"] = np.nan
    t["rel_gap_vs_areactyx0_over_ci"] = (t.lumen_crop - t.impact_phys).abs() / t.lumen_crop.abs().clip(lower=1e-30)
    t["rel_gap_vs_landx0"] = (t.lumen_crop - t.landx0_crop).abs() / t.lumen_crop.abs().clip(lower=1e-30)
    for k, g in t.groupby("cty"):
        w = g.loc[g.rel_gap_vs_areactyx0_over_ci.idxmax()]
        log(f"         {k}: LUMEN crop vs sum AREACTYX0 / CROPINTENS over {g.yrs.min()}-{g.yrs.max()}: "
            f"worst rel gap {w.rel_gap_vs_areactyx0_over_ci:.1e} in {w.yrs} "
            f"({w.lumen_crop:,.3f} vs {w.impact_phys:,.3f} kha; harvested {w.impact_harv:,.3f} kha, CI {w.crop_intens:.6f})"
            + (f"; vs LANDX0 crop worst {g.rel_gap_vs_landx0.max():.1e}" if g.landx0_crop.notna().any() else ""))
    return t


def write_targets_gdx(tg, jcrop, sys_, cty_run, yrs, path, gamsdir):
    """jcrop: the JCROP list shared with the crop GDX (IMPACT crops first, then AP-only crops)."""
    m = new_gdx(gamsdir)
    s_cty = gt.Set(m, "cty", records=sorted(cty_run), description="countries in LUMEN cty_run")
    s_j = gt.Set(m, "JCROP", records=jcrop, description="crops (IMPACT j-codes): IMPACT crops first, then crops only AP reports")
    s_s = gt.Set(m, "SYS", records=sys_, description="production system (IMPACT air -> IR, arf -> RF, AGG = IR + RF)")
    s_y = gt.Set(m, "yrs", records=[str(y) for y in yrs], description="LUMEN years")
    a = tg["area"]
    gt.Parameter(m, "area_harv_cty", domain=[s_cty, s_j, s_s, s_y], records=a[["cty", "j", "sys", "yrs", "value"]],
                 description="IMPACT AREACTYX0: harvested crop area by country, crop, system, year (1000 ha)")
    y = tg["yld"]
    gt.Parameter(m, "yield_cty", domain=[s_cty, s_j, s_s, s_y], records=y[["cty", "j", "sys", "yrs", "value"]],
                 description="IMPACT YLDCTYX0: yield by country, crop, system, year (t per harvested ha)")
    gt.Parameter(m, "crop_intens", domain=[s_cty, s_y], records=tg["ci"][["cty", "yrs", "value"]],
                 description="IMPACT cropping intensity: harvested area over physical cropland")
    land = tg["land"]
    gt.Parameter(m, "landx0_crop", domain=[s_cty, s_y], records=None if land.empty else land[["cty", "yrs", "value"]],
                 description="IMPACT LANDX0(cty,'crop',yrs): physical cropland (1000 ha); empty if the IMPACT file has no LANDX0")
    m.write(str(path))
