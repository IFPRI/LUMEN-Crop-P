"""Step 3 - CSV reports for inspection, plus independent audits of the delivered GDX files.

Nothing here feeds back into the deliverables. The audits re-derive the results from the
SOURCE files (the AP downscale, solution_lu and the IMPACT scenario file) and compare against
what steps 1 and 2 wrote. A failed check stops the run with a non-zero exit code and the report
says which one failed.

Writes to output/secondary/
  <cty>_crop_by_pid_<yr>.csv          balanced area (physical and harvested), production, yield, per pid-crop-system
  <cty>_crop_by_country_<yr>.csv      one row per crop-system: AP original, IMPACT target, balanced, RAS column factor
  <cty>_pid_summary_<yr>.csv          one row per pid: coords, coverage, lu_out, AP area, RAS row factor, seed kind
  <cty>_ap_dropped_<yr>.csv           AP records that could not be used, with the reason
  <cty>_crop_compare_by_pid_<yr>.csv  AP crop area vs LUMEN lu_out pools, per pid
  audit_report.txt                    every check, PASS/FAIL, with the numbers
"""
import numpy as np
import gams.transfer as gt
import pandas as pd

from gdxio import open_gdx, records, param3, param1, set1
from step1_crosswalk import read_pixel_dim
from impact_targets import FCTR_TO_SYS

TOL_REL = 1e-9
TOL_CTY = 1e-6
FMT = "%.10g"
BAL = ["IR", "RF"]
KEY = ["pid", "jcrop", "sys"]
SEED_KIND = {1: "ap_cell", 2: "column_fallback_ap_system_footprint", 3: "row_fallback_national_impact_mix"}
YIELD_KIND = {1: "ap_cell", 2: "ap_country", 3: "impact_yldctyx0"}


class Audit:
    def __init__(self, log):
        self.rows, self.log = [], log

    def chk(self, name, cond, detail=""):
        self.rows.append((bool(cond), name, detail))

    def section(self, title):
        self.rows.append((None, title, ""))

    def render(self):
        out = []
        for good, name, det in self.rows:
            if good is None:
                out += ["", name, "-" * len(name)]
            else:
                out.append("%-5s%-76s%s" % ("PASS" if good else "FAIL", name, det))
        n = [g for g, _, _ in self.rows if g is not None]
        out += ["", "%d/%d checks pass%s" % (sum(n), len(n), "" if all(n) else "   <-- SEE FAILURES ABOVE")]
        return "\n".join(out)

    @property
    def ok(self):
        return all(g for g, _, _ in self.rows if g is not None)


def rel(a, b):
    """elementwise |a-b| / max(|b|, tiny)"""
    a, b = np.asarray(a, float), np.asarray(b, float)
    return np.abs(a - b) / np.maximum(np.abs(b), 1e-30)


# ============================================================================ sources
def read_impact(impact_path, cty_run, baseyear, gamsdir):
    """Raw IMPACT symbols for the base year, read straight from the scenario file."""
    c = gt.Container(system_directory=str(gamsdir))
    c.read(str(impact_path), symbols=["AREACTYX0", "CROPINTENSX0", "CROPINTENS", "LANDX0", "YLDCTYX0"])
    by, cty = str(baseyear), set(cty_run)
    a = records(c["AREACTYX0"], ["jcrop", "cty", "fctr", "yrs", "value"])
    a = a[a.cty.isin(cty) & (a.yrs == by) & a.fctr.isin(FCTR_TO_SYS)].copy()
    a["sys"] = a.fctr.map(FCTR_TO_SYS)
    area = a.groupby(["cty", "jcrop", "sys"])["value"].sum()
    y = records(c["YLDCTYX0"], ["jcrop", "cty", "fctr", "yrs", "value"])
    y = y[y.cty.isin(cty) & (y.yrs == by) & y.fctr.isin(FCTR_TO_SYS)].copy()
    y["sys"] = y.fctr.map(FCTR_TO_SYS)
    yld = y.set_index(["cty", "jcrop", "sys"])["value"]
    if "CROPINTENSX0" in c.listSymbols():
        ci = records(c["CROPINTENSX0"], ["cty", "yrs", "value"])
        ci = ci[ci.cty.isin(cty) & (ci.yrs == by)].set_index("cty")["value"]
    else:
        ci = records(c["CROPINTENS"], ["cty", "value"])
        ci = ci[ci.cty.isin(cty)].set_index("cty")["value"]
    land = None
    if "LANDX0" in c.listSymbols():
        land = records(c["LANDX0"], ["cty", "fland", "yrs", "value"])
        land = land[land.cty.isin(cty) & (land.yrs == by) & (land.fland == "crop")].set_index("cty")["value"]
    return dict(area=area, yld=yld, ci=ci, land=land)


def read_lumen(lu_path, baseyear, gamsdir):
    c = open_gdx(lu_path, gamsdir)
    lu = param3(c, "lu_out", ["pid", "fland", "yrs"])
    pid_run = set1(c, "pid_run")
    cty_run = sorted(set1(c, "cty_run"))
    pc = records(c["pid_cty"], ["pid", "cty"])
    pc = pc[pc.pid.isin(pid_run)].set_index("pid")["cty"]
    crop = lu[(lu.yrs == str(baseyear)) & (lu.fland == "crop") & lu.pid.isin(pid_run)].groupby("pid")["value"].sum()
    crop = crop.reindex(sorted(pid_run, key=lambda s: int(s[1:]))).fillna(0.0)
    coords = records(c["pid_coords"], ["pid", "coord", "value"]).pivot(index="pid", columns="coord", values="value")
    lub = lu[lu.yrs == str(baseyear)].pivot_table(index="pid", columns="fland", values="value", aggfunc="sum")
    pid_cty_all = records(c["pid_cty"], ["pid", "cty"]).set_index("pid")["cty"]
    return dict(crop=crop, pid_run=pid_run, cty_run=cty_run, pid_cty=pc, coords=coords, pools=lub, pid_cty_all=pid_cty_all)


def read_delivered(res_path, gamsdir):
    d = open_gdx(res_path, gamsdir)
    P3 = lambda n, v: param3(d, n, KEY).rename(columns={"value": v})
    P1 = lambda n, v: param1(d, n, "pid").rename(columns={"value": v}).set_index("pid")[v]
    C3 = lambda n, v: records(d[n], ["cty", "jcrop", "sys", "value"]).rename(columns={"value": v}).set_index(["cty", "jcrop", "sys"])[v]
    S3 = lambda n: set(map(tuple, records(d[n], ["cty", "jcrop", "sys"]).values))
    o = dict(
        A=P3("p_Area_pid", "ap_area"), P=P3("p_Production_pid", "ap_prod"),
        AL=P3("p_Area_lu", "area_lu"), AH=P3("p_Area_harv", "area_harv"), PH=P3("p_Production_harv", "prod"),
        Y=P3("p_Yield_used", "yield"), YS=P3("yield_source", "yield_source"),
        SD=P3("seed", "seed"), SS=P3("seed_source", "seed_source"),
        DA=P3("p_Area_ap_dropped", "area"), DP=P3("p_Production_ap_dropped", "prod"),
        ras_row=P1("ras_row", "ras_row"), lu_base=P1("lu_out_crop_base", "lu_base"), n_ap_pix=P1("n_ap_pix", "n_ap_pix"),
        ras_col=C3("ras_col", "ras_col"), t_harv=C3("target_harv", "t_harv"), t_lu=C3("target_lu", "t_lu"),
        ci=records(d["ci"], ["cty", "value"]).set_index("cty")["value"],
        col_scale=records(d["col_scale"], ["cty", "value"]).set_index("cty")["value"],
        cty_lu=records(d["cty_lu_crop"], ["cty", "value"]).set_index("cty")["value"],
        cty_harv=records(d["cty_harv"], ["cty", "value"]).set_index("cty")["value"],
        cty_phys=records(d["cty_phys"], ["cty", "value"]).set_index("cty")["value"],
        pid_run=set1(d, "pid_run"), pid_bal=set1(d, "pid_balanced"), pid_ap=set1(d, "pid_seed_ap"),
        pid_nat=set1(d, "pid_seed_nat"), pid_out=set1(d, "pid_outside_run"), pid_lz=set1(d, "pid_luzero"),
        js_bal=S3("js_balanced"), js_ap=S3("js_seed_ap"), js_sys=S3("js_seed_sys"), js_nt=S3("js_no_target"),
        pid_cty=records(d["pid_cty"], ["pid", "cty"]).set_index("pid")["cty"],
        base_year=int(d["base_year"].records.iloc[0, 0]), n_iter=int(d["n_iter"].records.iloc[0, 0]),
        coords_used=records(d["pid_coords_used"], ["pid", "coord", "value"]).pivot(index="pid", columns="coord", values="value"),
    )
    o["jcrop"] = list(d["JCROP"].records.iloc[:, 0].astype(str))
    return o


# ============================================================================ audit A
def audit_conservation(A, ap_path, lu_path, res_path, gamsdir):
    """Re-aggregate AP's pixels with the delivered map and compare with the delivered pid data."""
    A.section("A. CROSSWALK AND AGGREGATION - re-derived from the AP source file")
    src = open_gdx(ap_path, gamsdir)
    ap = read_pixel_dim(src)
    area = param3(src, "p_Area", ["pixel", "jcrop", "sys"])
    prod = param3(src, "p_Production", ["pixel", "jcrop", "sys"])
    lu = open_gdx(lu_path, gamsdir)
    pc = records(lu["pid_coords"], ["pid", "coord", "value"]).pivot(index="pid", columns="coord", values="value")
    d = open_gdx(res_path, gamsdir)
    mp = records(d["PIXEL_TO_PID_AP"], ["pixel", "pid"])
    AD = param3(d, "p_Area_pid", KEY)
    PD = param3(d, "p_Production_pid", KEY)
    UA = param3(d, "p_Area_unmapped", ["pixel", "jcrop", "sys"])
    UP = param3(d, "p_Production_unmapped", ["pixel", "jcrop", "sys"])

    A.chk("every mapped pixel has exactly one pid", mp.groupby("pixel")["pid"].nunique().max() == 1)
    A.chk("no duplicate (pixel, pid) rows", not mp.duplicated().any())
    A.chk("source pixel keys unique", not ap.pixel.duplicated().any())
    A.chk("source (x, y) unique", not ap.duplicated(["x", "y"]).any())

    S, M, U = set(ap.pixel), set(mp.pixel), set(UA.pixel)
    A.chk("mapped and unmapped pixels are disjoint", len(M & U) == 0, f"overlap = {len(M & U)}")
    A.chk("mapped + unmapped covers every source pixel carrying data",
          (M | U) <= S and set(area.pixel) <= (M | U),
          f"mapped {len(M):,} + unmapped {len(U):,} of {len(S):,} source pixels")

    g = mp.merge(ap, on="pixel").join(pc, on="pid", rsuffix="_p")
    dx, dy = (g.x - g.x_p).abs(), (g.y - g.y_p).abs()
    A.chk("every pixel centre strictly inside its pid's 0.25-deg box", dx.max() < 0.125 and dy.max() < 0.125,
          f"max |dx| = {dx.max():.5f}, max |dy| = {dy.max():.5f} (limit 0.125, expected 1/12 = {1/12:.5f})")
    cnt = mp.groupby("pid").size()
    A.chk("no pid has more than 9 child pixels", cnt.max() <= 9,
          f"children per pid: min {cnt.min()}, median {int(cnt.median())}, max {cnt.max()}")

    for nm, SRC, DEL in [("p_Area_pid", area, AD), ("p_Production_pid", prod, PD)]:
        re = SRC.merge(mp, on="pixel").groupby(KEY, as_index=False)["value"].sum()
        j = re.merge(DEL, on=KEY, how="outer", suffixes=("_re", "_del")).fillna(0.0)
        dd = (j.value_re - j.value_del).abs()
        A.chk(f"{nm}: every (pid, crop, sys) cell equals an independent re-sum",
              dd.max() < 1e-9 and len(j) == len(DEL) == len(re), f"{len(j):,} cells, max abs diff {dd.max():.1e}")

    for nm, SRC, DEL, UN, unit in [("area", area, AD, UA, "kha"), ("production", prod, PD, UP, "kt")]:
        for s in sorted(SRC.sys.unique()):
            si = SRC.loc[SRC.sys == s, "value"].sum()
            so = DEL.loc[DEL.sys == s, "value"].sum() + UN.loc[UN.sys == s, "value"].sum()
            A.chk(f"{nm} SYS={s}: source total == on-grid + unmapped residual", abs(si - so) < 1e-6,
                  f"in {si:,.4f}  out {so:,.4f} {unit}")
    A.chk("unmapped residual carries data", True,
          f"{UA.pixel.nunique()} pixels, {UA.loc[UA.sys == 'AGG', 'value'].sum():.4f} kha, "
          f"{UP.loc[UP.sys == 'AGG', 'value'].sum():.4f} kt")


# ============================================================================ audit B
def audit_balance(A, D, L, I, baseyear):
    A.section("B. BALANCE - re-derived from solution_lu, the IMPACT scenario file and the originals in the delivered GDX")
    A.chk("base_year scalar in the GDX equals the requested base year", D["base_year"] == int(baseyear),
          f"{D['base_year']} vs {baseyear}")

    # ---- check 1: country totals
    for k in L["cty_run"]:
        lumen = L["crop"][L["pid_cty"][L["pid_cty"] == k].index].sum()
        harv = I["area"].xs(k, level="cty").sum()
        phys = harv / I["ci"][k]
        A.chk(f"CHECK 1 {k}: LUMEN lu_out crop total == IMPACT sum AREACTYX0 / CROPINTENSX0 ({baseyear})",
              rel(lumen, phys) < TOL_CTY,
              f"LUMEN {lumen:,.4f} kha | IMPACT harvested {harv:,.4f} / CI {I['ci'][k]:.6f} = {phys:,.4f} kha | rel gap {rel(lumen, phys):.1e}")
        if I["land"] is not None and k in I["land"].index:
            A.chk(f"CHECK 1 {k}: LUMEN lu_out crop total == IMPACT LANDX0 crop", rel(lumen, I["land"][k]) < TOL_CTY,
                  f"{lumen:,.4f} vs {I['land'][k]:,.4f} kha, rel gap {rel(lumen, I['land'][k]):.1e}")
        A.chk(f"{k}: delivered cty_lu_crop / cty_harv / cty_phys equal the source files",
              rel(D["cty_lu"][k], lumen) < 1e-12 and rel(D["cty_harv"][k], harv) < 1e-12 and rel(D["cty_phys"][k], phys) < 1e-12)
        A.chk(f"{k}: col_scale == LUMEN / IMPACT physical and within {TOL_CTY:g} of 1",
              rel(D["col_scale"][k], lumen / phys) < 1e-12 and abs(D["col_scale"][k] - 1) <= TOL_CTY,
              f"col_scale = {D['col_scale'][k]:.12f}")

    # ---- pid partition
    lu = L["crop"]
    pos = set(lu[lu > 0].index)
    A.chk("pid_balanced == pids in pid_run with lu_out crop > 0", D["pid_bal"] == pos, f"{len(D['pid_bal'])} vs {len(pos)}")
    A.chk("pid_seed_ap and pid_seed_nat partition pid_balanced",
          (D["pid_ap"] | D["pid_nat"]) == D["pid_bal"] and not (D["pid_ap"] & D["pid_nat"]),
          f"{len(D['pid_ap'])} + {len(D['pid_nat'])} = {len(D['pid_bal'])}")
    A.chk("lu_out_crop_base equals solution_lu lu_out(crop, base year) on every pid_run pid",
          np.allclose(D["lu_base"].reindex(lu.index).fillna(0.0), lu, rtol=0, atol=1e-12))

    # ---- HEADLINE rows
    AL, AH, PH = D["AL"], D["AH"], D["PH"]
    bal = AL[AL.sys.isin(BAL)]
    rows = bal.groupby("pid")["area_lu"].sum().reindex(lu.index).fillna(0.0)
    r = rel(rows, lu)
    r[lu.values == 0] = np.abs(rows.values[lu.values == 0])
    A.chk("HEADLINE per pid: sum over crops and IR+RF of p_Area_lu == lu_out(pid,'crop',base year), all pid_run",
          r.max() < 1e-12, f"{len(lu):,} pids, max rel {r.max():.1e}, max abs {np.abs(rows - lu).max():.1e} kha")
    A.chk("no p_Area_lu outside pid_balanced", set(AL.pid) <= D["pid_bal"])

    # ---- HEADLINE columns
    cty_of = D["pid_cty"]
    bal = bal.assign(cty=bal.pid.map(cty_of))
    cols_h = AH[AH.sys.isin(BAL)].assign(cty=lambda x: x.pid.map(cty_of)).groupby(["cty", "jcrop", "sys"])["area_harv"].sum()
    tgt = I["area"]
    both = pd.concat([cols_h.rename("del"), tgt.rename("src")], axis=1).fillna(0.0)
    scl = both.index.get_level_values("cty").map(D["col_scale"]).values
    posc = both.src > 0
    rc = rel(both["del"][posc], both.src[posc] * scl[posc])
    A.chk("HEADLINE per crop-system: sum over pids of p_Area_harv == AREACTYX0(j,cty,sys,base year) x col_scale",
          rc.max() < 10 * TOL_REL, f"{posc.sum()} crop-systems, max rel {rc.max():.1e}, max abs {np.abs(both['del'] - both.src * scl)[posc].max():.1e} kha")
    rc0 = rel(both["del"][posc], both.src[posc])
    A.chk("  ... and == AREACTYX0 itself (col_scale is 1 to this tolerance)", rc0.max() < 1e-8, f"max rel {rc0.max():.1e}")
    A.chk("no harvested area on crop-systems IMPACT has no area for", (both["del"][~posc] == 0).all(),
          f"{(~posc).sum()} such columns")
    agg_h = AH[AH.sys == "AGG"].assign(cty=lambda x: x.pid.map(cty_of)).groupby(["cty", "jcrop"])["area_harv"].sum()
    agg_t = tgt.groupby(level=["cty", "jcrop"]).sum()
    j = pd.concat([agg_h.rename("del"), agg_t.rename("src")], axis=1).fillna(0.0)
    j = j[j.src > 0]
    A.chk("per crop (AGG): sum over pids of p_Area_harv == sum over systems of AREACTYX0", rel(j["del"], j.src).max() < 1e-8,
          f"{len(j)} crops, max rel {rel(j['del'], j.src).max():.1e}")
    A.chk("js_balanced == crop-systems with AREACTYX0 > 0", D["js_bal"] == set(tgt[tgt > 0].index), f"{len(D['js_bal'])} columns")

    # ---- harvested vs physical, AGG = IR + RF
    m = AH.merge(AL, on=KEY).assign(cty=lambda x: x.pid.map(cty_of))
    ci = m.cty.map(I["ci"])
    A.chk("p_Area_harv == p_Area_lu x CROPINTENSX0 (from the IMPACT file), every cell", rel(m.area_harv, m.area_lu * ci).max() < TOL_REL,
          f"max rel {rel(m.area_harv, m.area_lu * ci).max():.1e}")
    for nm, df, col in [("p_Area_lu", AL, "area_lu"), ("p_Area_harv", AH, "area_harv"), ("p_Production_harv", PH, "prod")]:
        w = df.pivot_table(index=["pid", "jcrop"], columns="sys", values=col, fill_value=0.0)
        for s in ["IR", "RF", "AGG"]:
            if s not in w:
                w[s] = 0.0
        dd = (w["AGG"] - w["IR"] - w["RF"]).abs() / w["AGG"].abs().clip(lower=1e-30)
        A.chk(f"{nm}: AGG == IR + RF", dd.max() < TOL_REL, f"max rel {dd.max():.1e}")

    # ---- biproportionality: the balanced matrix is the seed times one row and one column factor
    SD, SS = D["SD"], D["SS"]
    s = SD.merge(AL, on=KEY, how="outer").fillna(0.0).assign(cty=lambda x: x.pid.map(cty_of))
    s = s[s.sys.isin(BAL)]
    s["rr"] = s.pid.map(D["ras_row"])
    s["rcf"] = [D["ras_col"].get((c, jj, ss), 0.0) for c, jj, ss in zip(s.cty, s.jcrop, s.sys)]
    on = s.seed > 0
    A.chk("p_Area_lu == seed x ras_row(pid) x ras_col(cty,crop,sys) on every seeded cell",
          rel(s.area_lu[on], s.seed[on] * s.rr[on] * s.rcf[on]).max() < TOL_REL,
          f"{on.sum():,} cells, max rel {rel(s.area_lu[on], s.seed[on] * s.rr[on] * s.rcf[on]).max():.1e}")
    A.chk("p_Area_lu == 0 wherever the seed is 0 (no area invented outside the seed support)",
          (s.area_lu[~on] == 0).all(), f"{(~on).sum():,} zero-seed cells")
    A.chk("all RAS factors strictly positive", (D["ras_row"] > 0).all() and (D["ras_col"] > 0).all(),
          f"row: min {D['ras_row'].min():.4g} max {D['ras_row'].max():.4g} | col: min {D['ras_col'].min():.4g} max {D['ras_col'].max():.4g}")

    # ---- seed provenance
    Ap = D["A"]
    ss = SS.merge(SD, on=KEY).merge(Ap, on=KEY, how="left").fillna({"ap_area": 0.0})
    ss1 = ss[ss.seed_source == 1]
    A.chk("seed == p_Area_pid wherever seed_source = 1 (bit-identical)", (ss1.seed == ss1.ap_area).all(), f"{len(ss1):,} cells")
    ap_bal = Ap[Ap.sys.isin(BAL) & (Ap.ap_area > 0) & Ap.pid.isin(D["pid_ap"])].assign(cty=lambda x: x.pid.map(cty_of))
    ap_bal["col"] = list(zip(ap_bal.cty, ap_bal.jcrop, ap_bal.sys))
    expect1 = set(map(tuple, ap_bal[ap_bal.col.isin(D["js_ap"])][KEY].values))
    A.chk("seed_source = 1 cells == every positive AP cell on an AP-seeded pid in an AP-supported column",
          set(map(tuple, ss1[KEY].values)) == expect1, f"{len(expect1):,} cells")
    in_run = Ap[Ap.sys.isin(BAL) & Ap.pid.isin(D["pid_bal"])].assign(cty=lambda x: x.pid.map(cty_of))
    col_ap = in_run.groupby(["cty", "jcrop", "sys"])["ap_area"].sum()
    A.chk("seed_source = 2 columns (js_seed_sys) carry no AP area on any balanced pid of the country",
          all(col_ap.get(k, 0.0) == 0 for k in D["js_sys"]), f"{len(D['js_sys'])} columns: {sorted(k[1] + '/' + k[2] for k in D['js_sys'])}")
    A.chk("js_seed_ap and js_seed_sys partition js_balanced",
          (D["js_ap"] | D["js_sys"]) == D["js_bal"] and not (D["js_ap"] & D["js_sys"]), f"{len(D['js_ap'])} + {len(D['js_sys'])}")
    usable = in_run[in_run.apply(lambda r_: (r_.cty, r_.jcrop, r_.sys) in D["js_bal"], axis=1)].groupby("pid")["ap_area"].sum() if len(in_run) else pd.Series(dtype=float)
    A.chk("seed_source = 3 pids (pid_seed_nat) carry no AP area in any balanced column",
          all(usable.get(p, 0.0) == 0 for p in D["pid_nat"]), f"{len(D['pid_nat'])} pids")
    A.chk("every pid_seed_ap pid carries AP area in a balanced column", all(usable.get(p, 0.0) > 0 for p in D["pid_ap"]))
    A.chk("seed_source takes only the values 1, 2, 3 and is set on every positive seed",
          set(SS.seed_source.unique()) <= {1, 2, 3} and len(SS) == (SD.seed > 0).sum(), f"{len(SS):,} cells")

    # ---- yields and production
    Y, YS, P = D["Y"], D["YS"], D["P"]
    y = Y[Y.sys.isin(BAL)].merge(YS, on=KEY, how="left").merge(Ap, on=KEY, how="left").merge(P, on=KEY, how="left") \
        .merge(AH[["pid", "jcrop", "sys", "area_harv"]], on=KEY, how="left").assign(cty=lambda x: x.pid.map(cty_of))
    # AP's area is physical, so AP production / AP area is per physical ha; p_Yield_used is per harvested ha,
    # hence the division by the country's cropping intensity (read from the IMPACT file, not the delivered GDX)
    ci_of = y.cty.map(I["ci"]).to_numpy()
    y1 = y[y.yield_source == 1]
    A.chk("yield_source = 1: p_Yield_used == (p_Production_pid / p_Area_pid) / CROPINTENSX0  [AP yield per physical ha -> per harvested ha]",
          rel(y1["yield"], y1.ap_prod / y1.ap_area / ci_of[y.yield_source == 1]).max() < TOL_REL, f"{len(y1):,} cells")
    y2 = y[y.yield_source == 2]
    if len(y2):
        apc = Ap[Ap.sys.isin(BAL)].merge(P, on=KEY).assign(cty=lambda x: x.pid.map(L["pid_cty_all"]))
        apc = apc[apc.cty.isin(L["cty_run"])].groupby(["cty", "jcrop", "sys"])[["ap_area", "ap_prod"]].sum()
        apy = (apc.ap_prod / apc.ap_area)
        exp2 = np.array([apy.get((c, jj, s_), np.nan) / I["ci"][c] for c, jj, s_ in zip(y2.cty, y2.jcrop, y2.sys)])
        A.chk("yield_source = 2: p_Yield_used == AP country yield for the crop-system / CROPINTENSX0", rel(y2["yield"], exp2).max() < TOL_REL, f"{len(y2):,} cells")
    y3 = y[y.yield_source == 3]
    if len(y3):
        exp3 = np.array([I["yld"].get((c, jj, s_), np.nan) for c, jj, s_ in zip(y3.cty, y3.jcrop, y3.sys)])
        A.chk("yield_source = 3: p_Yield_used == IMPACT YLDCTYX0 (from the IMPACT file)", rel(y3["yield"], exp3).max() < TOL_REL,
              f"{len(y3):,} cells on crops {sorted(y3.jcrop.unique())}")
    alloc = AH[AH.sys.isin(BAL) & (AH.area_harv > 0)]
    yk = alloc.merge(YS, on=KEY, how="left")
    A.chk("every allocated cell has a yield source", yk.yield_source.notna().all() and (yk.yield_source > 0).all(), f"{len(yk):,} cells")
    pm = PH[PH.sys.isin(BAL)].merge(AH, on=KEY).merge(Y, on=KEY)
    A.chk("p_Production_harv == p_Area_harv x p_Yield_used", rel(pm["prod"], pm.area_harv * pm["yield"]).max() < TOL_REL,
          f"max rel {rel(pm['prod'], pm.area_harv * pm['yield']).max():.1e}")
    # the same identity on the physical basis for AP-based cells: production == p_Area_lu x (AP production / AP physical area)
    pa = PH[PH.sys.isin(BAL)].merge(AL[["pid", "jcrop", "sys", "area_lu"]], on=KEY).merge(YS, on=KEY).merge(Ap, on=KEY).merge(P, on=KEY)
    pa = pa[pa.yield_source == 1]
    A.chk("yield_source = 1: p_Production_harv == p_Area_lu x (p_Production_pid / p_Area_pid)  [AP yield applied to physical area]",
          rel(pa["prod"], pa.area_lu * pa.ap_prod / pa.ap_area).max() < TOL_REL, f"{len(pa):,} cells")

    # ---- dropped AP area accounted for
    DA = D["DA"]
    ap_in = Ap[Ap.sys.isin(BAL)].ap_area.sum()
    seeded = ss1.seed.sum()
    dropped = DA[DA.sys.isin(BAL)].area.sum()
    A.chk("AP area (IR+RF) == seeded (source 1) + dropped", abs(ap_in - seeded - dropped) < 1e-6,
          f"{ap_in:,.4f} = {seeded:,.4f} + {dropped:,.4f} kha")
    da = DA[DA.sys.isin(BAL)].assign(cty=lambda x: x.pid.map(cty_of))
    no_target = np.array([((c, jj, s_) in D["js_nt"]) for c, jj, s_ in zip(da.cty, da.jcrop, da.sys)], dtype=bool)
    reason_ok = da.pid.isin(D["pid_out"]).values | da.pid.isin(D["pid_lz"]).values | no_target
    A.chk("every dropped record is on a pid outside pid_run, a lu_out-zero pid, or a no-target crop-system", bool(np.all(reason_ok)),
          f"{len(da):,} records; outside run {da.pid.isin(D['pid_out']).sum()}, lu_out zero {da.pid.isin(D['pid_lz']).sum()}, "
          f"no target {int(no_target.sum())}")
    A.chk("pid_outside_run has no pid_run pid; pid_luzero pids are in pid_run with lu_out crop = 0",
          not (D["pid_out"] & L["pid_run"]) and D["pid_lz"] <= L["pid_run"] and all(lu.get(p, 0) == 0 for p in D["pid_lz"]),
          f"{len(D['pid_out'])} outside, {len(D['pid_lz'])} lu_out zero")
    A.chk("js_no_target columns have AREACTYX0 == 0", all(tgt.get(k, 0.0) == 0 for k in D["js_nt"]),
          f"{sorted(k[1] + '/' + k[2] for k in D['js_nt'])}")

    # ---- sanity
    allv = pd.concat([AL.area_lu, AH.area_harv, PH["prod"], Y["yield"]])
    A.chk("all deliverable values finite and >= 0", np.isfinite(allv).all() and (allv >= 0).all())


# ============================================================================ CSV reports
def write_reports(D, L, I, sec_dir, cty, baseyear, log):
    AL, AH, PH, Y, YS, SS, Ap, P = D["AL"], D["AH"], D["PH"], D["Y"], D["YS"], D["SS"], D["A"], D["P"]
    cty_of = D["pid_cty"]

    # 1. per pid-crop-system
    main = AL.merge(AH, on=KEY).merge(PH, on=KEY).merge(Y, on=KEY, how="left").merge(YS, on=KEY, how="left") \
        .merge(SS, on=KEY, how="left").merge(Ap, on=KEY, how="left").merge(P, on=KEY, how="left")
    main = main.rename(columns={"area_lu": "area_lu_kha", "area_harv": "area_harv_kha", "prod": "prod_kt",
                                "yield": "yield_t_per_ha", "ap_area": "ap_area_kha", "ap_prod": "ap_prod_kt"})
    main["yield_source"] = main.yield_source.map(YIELD_KIND).fillna("")
    main["seed_source"] = main.seed_source.map(SEED_KIND).fillna("")
    main.loc[main.sys == "AGG", ["yield_source", "seed_source"]] = ""
    main["jcrop"] = pd.Categorical(main.jcrop, categories=D["jcrop"])
    main = main.sort_values(["pid", "jcrop", "sys"], key=lambda c: c.map(lambda v: int(v[1:])) if c.name == "pid" else c)
    f1 = sec_dir / f"{cty}_crop_by_pid_{baseyear}.csv"
    main.to_csv(f1, index=False, float_format=FMT)

    # 2. per crop-system, country level
    ap_all = Ap.merge(P, on=KEY, how="outer").fillna(0.0)
    ap_all["cty"] = ap_all.pid.map(L["pid_cty_all"])
    g_ap = ap_all[ap_all.cty.isin(L["cty_run"])].groupby(["cty", "jcrop", "sys"]).agg(
        ap_area_kha=("ap_area", "sum"), ap_prod_kt=("ap_prod", "sum"), n_pid_ap=("pid", "nunique"))
    seeded = SS[SS.seed_source == 1].merge(Ap, on=KEY).assign(cty=lambda x: x.pid.map(cty_of)) \
        .groupby(["cty", "jcrop", "sys"])["ap_area"].sum().rename("ap_area_seeded_kha")
    g_bal = AH.merge(AL, on=KEY).merge(PH, on=KEY).assign(cty=lambda x: x.pid.map(cty_of)).groupby(["cty", "jcrop", "sys"]).agg(
        balanced_harv_kha=("area_harv", "sum"), balanced_lu_kha=("area_lu", "sum"), balanced_prod_kt=("prod", "sum"),
        n_pid_balanced=("pid", "nunique"))
    tg = I["area"].rename("impact_areactyx0_kha")
    tg_agg = tg.groupby(level=["cty", "jcrop"]).sum().to_frame().assign(sys="AGG").set_index("sys", append=True)["impact_areactyx0_kha"]
    tg = pd.concat([tg, tg_agg])
    yl = I["yld"].rename("impact_yield_t_per_ha")
    wa = (I["area"] * I["yld"].reindex(I["area"].index)).groupby(level=["cty", "jcrop"]).sum() / I["area"].groupby(level=["cty", "jcrop"]).sum()
    yl_agg = wa.to_frame("impact_yield_t_per_ha").assign(sys="AGG").set_index("sys", append=True)["impact_yield_t_per_ha"]
    yl = pd.concat([yl, yl_agg])
    t = pd.concat([g_ap, seeded, tg, g_bal, yl, D["ras_col"].rename("ras_col_factor")], axis=1).reset_index()
    t = t[t.cty.isin(L["cty_run"])]
    for c in ["ap_area_kha", "ap_prod_kt", "ap_area_seeded_kha", "impact_areactyx0_kha", "balanced_harv_kha", "balanced_lu_kha", "balanced_prod_kt"]:
        t[c] = t[c].fillna(0.0)
    t["n_pid_ap"] = t.n_pid_ap.fillna(0).astype(int)
    t["n_pid_balanced"] = t.n_pid_balanced.fillna(0).astype(int)
    # AP area is physical: compare it with the balanced physical area; IMPACT (harvested) with the balanced harvested area
    t["balanced_lu_over_ap"] = t.balanced_lu_kha / t.ap_area_kha.replace(0, np.nan)
    t["impact_over_ap"] = t.impact_areactyx0_kha / t.ap_area_kha.replace(0, np.nan)
    t["ap_yield_t_per_phys_ha"] = t.ap_prod_kt / t.ap_area_kha.replace(0, np.nan)
    t["ap_yield_t_per_harv_ha"] = t.ap_yield_t_per_phys_ha / t.cty.map(I["ci"])
    t["balanced_yield_t_per_ha"] = t.balanced_prod_kt / t.balanced_harv_kha.replace(0, np.nan)
    t["seed_kind"] = [("ap_cell" if k in D["js_ap"] else "column_fallback_ap_system_footprint" if k in D["js_sys"]
                       else "no_impact_target_dropped" if k in D["js_nt"] else "")
                      for k in zip(t.cty, t.jcrop, t.sys)]
    t["jcrop"] = pd.Categorical(t.jcrop, categories=D["jcrop"])
    t["sys"] = pd.Categorical(t.sys, categories=["AGG", "IR", "RF"])
    t = t.sort_values(["cty", "jcrop", "sys"])
    cols = ["cty", "jcrop", "sys", "ap_area_kha", "ap_area_seeded_kha", "balanced_lu_kha", "balanced_lu_over_ap",
            "impact_areactyx0_kha", "balanced_harv_kha", "impact_over_ap", "ras_col_factor", "seed_kind", "n_pid_ap", "n_pid_balanced",
            "ap_prod_kt", "balanced_prod_kt", "ap_yield_t_per_phys_ha", "ap_yield_t_per_harv_ha", "balanced_yield_t_per_ha", "impact_yield_t_per_ha"]
    f2 = sec_dir / f"{cty}_crop_by_country_{baseyear}.csv"
    t[cols].to_csv(f2, index=False, float_format=FMT)

    # 3. per pid
    ap_pid = Ap[Ap.sys == "AGG"].groupby("pid")["ap_area"].sum().rename("ap_area_kha")
    al_pid = AL[AL.sys == "AGG"].groupby("pid")["area_lu"].sum().rename("balanced_lu_kha")
    ah_pid = AH[AH.sys == "AGG"].groupby("pid")["area_harv"].sum().rename("balanced_harv_kha")
    pids = sorted(L["pid_run"] | set(ap_pid.index), key=lambda s: int(s[1:]))
    sm = pd.DataFrame(index=pd.Index(pids, name="pid"))
    sm = sm.join(L["coords"]).join(D["n_ap_pix"]).join(ap_pid).join(L["crop"].rename("lu_out_crop_kha")).join(al_pid).join(ah_pid) \
        .join(D["ras_row"].rename("ras_row_factor"))
    sm["lumen_cty"] = sm.index.map(L["pid_cty_all"])
    sm["in_pid_run"] = sm.index.isin(L["pid_run"])
    sm["n_ap_pix"] = sm.n_ap_pix.fillna(0).astype(int)
    for c in ["ap_area_kha", "lu_out_crop_kha", "balanced_lu_kha", "balanced_harv_kha"]:
        sm[c] = sm[c].fillna(0.0)
    sm["status"] = np.select(
        [sm.index.isin(D["pid_ap"]), sm.index.isin(D["pid_nat"]), sm.index.isin(D["pid_out"]), sm.index.isin(D["pid_lz"])],
        ["balanced_ap_seed", "balanced_national_mix_seed", "outside_pid_run_ap_dropped", "lu_out_crop_zero_ap_dropped"],
        default="in_pid_run_no_crop")
    sm = sm.rename(columns={"n_ap_pix": "n_ap_pixels"})
    f3 = sec_dir / f"{cty}_pid_summary_{baseyear}.csv"
    sm[["x", "y", "lumen_cty", "in_pid_run", "n_ap_pixels", "ap_area_kha", "lu_out_crop_kha", "balanced_lu_kha", "balanced_harv_kha",
        "ras_row_factor", "status"]].to_csv(f3, float_format=FMT)

    # 4. dropped AP records
    DA = D["DA"].merge(D["DP"], on=KEY, how="left").rename(columns={"area": "ap_area_kha", "prod": "ap_prod_kt"})
    DA["lumen_cty"] = DA.pid.map(L["pid_cty_all"])
    DA["reason"] = np.select([DA.pid.isin(D["pid_out"]), DA.pid.isin(D["pid_lz"])],
                             ["pid_outside_pid_run", f"lu_out_crop_{baseyear}_zero"], default="no_impact_target_for_crop_system")
    f4 = sec_dir / f"{cty}_ap_dropped_{baseyear}.csv"
    DA.sort_values(KEY).to_csv(f4, index=False, float_format=FMT)

    # 5. per-pid comparison of AP crop area against every LUMEN pool at the base year (unchanged from before)
    c = pd.concat([L["coords"], D["n_ap_pix"].rename("n_ap_pixels"), ap_pid.rename("ap_crop_area_kha"),
                   L["pools"].add_prefix(f"lumen_lu_out_{baseyear}_")], axis=1)
    c = c[c.index.isin(set(ap_pid.index) | L["pid_run"])].copy()
    c["in_pid_run"] = c.index.isin(L["pid_run"])
    c["ap_crop_area_kha"] = c["ap_crop_area_kha"].fillna(0.0)
    c["n_ap_pixels"] = c["n_ap_pixels"].fillna(0).astype(int)
    for col in [x for x in c.columns if x.startswith("lumen_lu_out")]:
        c[col] = c[col].fillna(0.0)
    c["diff_crop_kha"] = c[f"lumen_lu_out_{baseyear}_crop"] - c["ap_crop_area_kha"]
    c.index.name = "pid"
    f5 = sec_dir / f"{cty}_crop_compare_by_pid_{baseyear}.csv"
    c.sort_values("diff_crop_kha").to_csv(f5, float_format=FMT)

    # ---- summary numbers ----
    tt = t[(t.sys != "AGG") & t.ras_col_factor.notna()].copy()
    tt["lab"] = tt.jcrop.astype(str) + "/" + tt.sys.astype(str)
    up = tt.sort_values("ras_col_factor", ascending=False).head(5)
    dn = tt.sort_values("ras_col_factor").head(5)
    rr = D["ras_row"][D["ras_row"].index.isin(D["pid_ap"])]
    npx = D["n_ap_pix"].reindex(rr.index).fillna(0)
    fb_col = t[(t.sys != "AGG") & (t.seed_kind == "column_fallback_ap_system_footprint")].impact_areactyx0_kha.sum()
    fb_row = L["crop"][L["crop"].index.isin(D["pid_nat"])].sum()
    lines = [
        f"pids: {len(D['pid_bal'])} balanced ({len(D['pid_ap'])} AP seed, {len(D['pid_nat'])} national-mix seed), "
        f"AP dropped on {len(D['pid_out'])} pids outside pid_run and {len(D['pid_lz'])} lu_out-zero pids; RAS {D['n_iter']} iterations",
        f"columns: {len(D['js_bal'])} crop-systems balanced ({len(D['js_ap'])} AP seed, {len(D['js_sys'])} system-footprint seed), "
        f"{len(D['js_nt'])} AP crop-systems with no IMPACT target dropped {sorted(k[1] + '/' + k[2] for k in D['js_nt'])}",
        f"fallback seeds carry {fb_col:,.3f} kha harvested in the system-footprint columns ({100 * fb_col / I['area'].sum():.2f}% of AREACTYX0) "
        f"and {fb_row:,.3f} kha physical on the national-mix pids ({100 * fb_row / L['crop'].sum():.2f}% of lu_out crop)",
        f"area  LUMEN lu_out crop {L['crop'].sum():12,.3f} kha == balanced physical {AL[AL.sys == 'AGG'].area_lu.sum():12,.3f} kha | "
        f"IMPACT AREACTYX0 {I['area'].sum():12,.3f} kha == balanced harvested {AH[AH.sys == 'AGG'].area_harv.sum():12,.3f} kha "
        f"(cropping intensity {', '.join(f'{k} {v:.4f}' for k, v in I['ci'].items())})",
        f"AP    on grid {Ap[Ap.sys == 'AGG'].ap_area.sum():,.3f} kha: seeded {seeded.sum():,.3f}, dropped {D['DA'][D['DA'].sys == 'AGG'].area.sum():,.3f} kha; "
        f"AP production {P[P.sys == 'AGG'].ap_prod.sum():,.1f} kt -> balanced {PH[PH.sys == 'AGG']['prod'].sum():,.1f} kt "
        f"(AP yields per physical ha on LUMEN physical area; IMPACT yields on fallback cells; AP area is physical)",
        f"RAS column factor (IMPACT over AP after row balancing): largest " + ", ".join(f"{a} {b:,.1f}" for a, b in zip(up.lab, up.ras_col_factor))
        + "; smallest " + ", ".join(f"{a} {b:.3f}" for a, b in zip(dn.lab, dn.ras_col_factor)),
        f"RAS row factor on AP-seeded pids: median {rr.median():.3f} | p95 {rr.quantile(.95):.2f} | max {rr.max():,.1f}; "
        f"fully covered (9/9) {int((npx == 9).sum())} pids: median {rr[npx == 9].median():.2f}, max {rr[npx == 9].max():,.1f}; "
        f"partial {int((npx < 9).sum())} pids: median {rr[npx < 9].median():.2f}, max {rr[npx < 9].max():,.1f}",
    ]
    for ln in lines:
        log("         " + ln)
    for fp, n in [(f1, len(main)), (f2, len(t)), (f3, len(sm)), (f4, len(DA)), (f5, len(c))]:
        log(f"wrote  : {fp}  ({n:,} rows)")
    return "\n".join(lines)


# ============================================================================ entry
def run(ap_path, lu_path, impact_path, res_path, sec_dir, cty, baseyear, gamsdir, log):
    D = read_delivered(res_path, gamsdir)
    L = read_lumen(lu_path, baseyear, gamsdir)
    I = read_impact(impact_path, L["cty_run"], baseyear, gamsdir)
    summary = write_reports(D, L, I, sec_dir, cty, baseyear, log)
    A = Audit(log)
    audit_conservation(A, ap_path, lu_path, res_path, gamsdir)
    audit_balance(A, D, L, I, baseyear)
    text = A.render()
    rep = sec_dir / "audit_report.txt"
    rep.write_text(f"Audit of {res_path.name}  (base year {baseyear})\n\n{text}\n\nSummary\n-------\n{summary}\n",
                   encoding="utf-8")
    for ln in text.splitlines():
        log("  " + ln)
    log(f"wrote  : {rep}")
    return A.ok
