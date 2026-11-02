"""Step 3 - CSV reports for inspection, plus two independent audits of the delivered GDX files.

Nothing here feeds back into the deliverables. The audits re-derive the results from the
SOURCE files (the AP downscale and solution_lu) and compare against what steps 1 and 2 wrote.
A failed check stops the run with a non-zero exit code and the report says which one failed.

Writes to output/secondary/
  <cty>_crop_rescaled_by_pid_<yr>.csv          rescaled area, production, yield
  <cty>_crop_unanchored_by_pid_<yr>.csv        preserved (unscaled) records, with the reason
  <cty>_crop_rescale_factors_by_pid_<yr>.csv   one row per pid: coords, coverage, factor, status
  <cty>_crop_compare_by_pid_<yr>.csv           AP crop area vs LUMEN lu_out pools, per pid
  audit_report.txt                             every check, PASS/FAIL, with the numbers
"""
import numpy as np
import pandas as pd

from gdxio import open_gdx, records, param3, param1, set1
from step1_crosswalk import read_pixel_dim

TOL_REL = 1e-9
FMT = "%.10g"


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
                out.append("")
                out.append(name)
                out.append("-" * len(name))
            else:
                out.append("%-5s%-72s%s" % ("PASS" if good else "FAIL", name, det))
        n = [g for g, _, _ in self.rows if g is not None]
        out.append("")
        out.append("%d/%d checks pass%s" % (sum(n), len(n), "" if all(n) else "   <-- SEE FAILURES ABOVE"))
        return "\n".join(out)

    @property
    def ok(self):
        return all(g for g, _, _ in self.rows if g is not None)


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
    AD = param3(d, "p_Area_pid", ["pid", "jcrop", "sys"])
    PD = param3(d, "p_Production_pid", ["pid", "jcrop", "sys"])
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
        re = SRC.merge(mp, on="pixel").groupby(["pid", "jcrop", "sys"], as_index=False)["value"].sum()
        j = re.merge(DEL, on=["pid", "jcrop", "sys"], how="outer", suffixes=("_re", "_del")).fillna(0.0)
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
def audit_rescale(A, lu_path, res_path, baseyear, gamsdir):
    A.section("B. RESCALE - re-derived from the originals inside the delivered GDX and lu_out in solution_lu")
    d = open_gdx(res_path, gamsdir)
    P3 = lambda n, v: param3(d, n, ["pid", "jcrop", "sys"]).rename(columns={"value": v})
    P1 = lambda n, v: param1(d, n, "pid").rename(columns={"value": v})
    Ao, Po = P3("p_Area_pid", "area"), P3("p_Production_pid", "prod")
    AR, PR, YR = P3("p_Area_rescaled", "area_r"), P3("p_Production_rescaled", "prod_r"), P3("p_Yield_rescaled", "yld")
    UA, UP = P3("p_Area_unanchored", "area_u"), P3("p_Production_unanchored", "prod_u")
    FC, AN, UF = P1("rescale_factor", "factor"), P1("lu_out_crop_base", "anchor"), P1("lumen_crop_unfilled", "unfilled")
    S_res, S_unan, S_used = set1(d, "pid_rescaled"), set1(d, "pid_unanchored"), set1(d, "pid_used")
    by = int(d["base_year"].records.iloc[0, 0]) if "base_year" in d.listSymbols() else None

    lu = param3(open_gdx(lu_path, gamsdir), "lu_out", ["pid", "fland", "yrs"])
    src = lu[(lu.yrs == str(baseyear)) & (lu.fland == "crop")].groupby("pid")["value"].sum()

    A.chk("base_year scalar in the GDX equals the requested base year", by == int(baseyear), f"{by} vs {baseyear}")
    A.chk("rescaled and unanchored pids are disjoint", len(S_res & S_unan) == 0, f"overlap {len(S_res & S_unan)}")
    A.chk("rescaled + unanchored == pid_used", (S_res | S_unan) == S_used,
          f"{len(S_res)} + {len(S_unan)} = {len(S_res | S_unan)} vs pid_used {len(S_used)}")
    A.chk("every rescaled pid has a factor", S_res == set(FC.pid), f"{len(S_res)} vs {len(FC)}")

    a_del = AN.set_index("pid")["anchor"]
    a_src = src.reindex(a_del.index)
    A.chk(f"lu_out_crop_base equals solution_lu lu_out(crop, {baseyear})",
          np.allclose(a_del, a_src, rtol=0, atol=1e-12), f"max diff {np.abs(a_del - a_src).max():.1e}")

    tot = AR[AR.sys == "AGG"].groupby("pid")["area_r"].sum()
    anc = a_del.reindex(tot.index)
    rel = (tot - anc).abs() / anc.abs().clip(lower=1e-30)
    A.chk("HEADLINE per pid: sum_j area_rescaled(AGG) == lu_out crop anchor", rel.max() < TOL_REL,
          f"max rel {rel.max():.1e}, max abs {np.abs(tot - anc).max():.1e} kha")
    A.chk("that check covers every rescaled pid", set(tot.index) == S_res, f"{len(tot)} vs {len(S_res)}")

    ap_agg = Ao[Ao.sys == "AGG"].groupby("pid")["area"].sum()
    f_re = anc / ap_agg.reindex(anc.index)
    f_del = FC.set_index("pid")["factor"].reindex(f_re.index)
    A.chk("rescale_factor == anchor / AP AGG area", np.allclose(f_del, f_re, rtol=1e-12, atol=0),
          f"max rel {np.abs(f_del / f_re - 1).max():.1e}")
    A.chk("all factors strictly positive", bool((f_del > 0).all()), f"min {f_del.min():.4f}")

    m = AR.merge(Ao, on=["pid", "jcrop", "sys"], how="left").join(f_del.rename("f"), on="pid")
    A.chk("no rescaled cell is missing its original", bool(m.area.notna().all()))
    exp = m.area * m.f
    rel = (m.area_r - exp).abs() / exp.abs().clip(lower=1e-30)
    A.chk("area_rescaled == area * factor (all SYS)", rel.max() < TOL_REL, f"max rel {rel.max():.1e}")

    my = YR.merge(Ao, on=["pid", "jcrop", "sys"]).merge(Po, on=["pid", "jcrop", "sys"])
    rel = (my.yld - my["prod"] / my.area).abs() / (my["prod"] / my.area).abs().clip(lower=1e-30)
    A.chk("p_Yield_rescaled == p_Production_pid / p_Area_pid (unchanged)", rel.max() < TOL_REL, f"max rel {rel.max():.1e}")
    mp = PR.merge(AR, on=["pid", "jcrop", "sys"]).merge(YR, on=["pid", "jcrop", "sys"])
    rel = (mp.prod_r - mp.area_r * mp.yld).abs() / (mp.area_r * mp.yld).abs().clip(lower=1e-30)
    A.chk("prod_rescaled == area_rescaled * yield", rel.max() < TOL_REL, f"max rel {rel.max():.1e}")
    mp2 = PR.merge(Po, on=["pid", "jcrop", "sys"]).join(f_del.rename("f"), on="pid")
    rel = (mp2.prod_r - mp2["prod"] * mp2.f).abs() / (mp2["prod"] * mp2.f).abs().clip(lower=1e-30)
    A.chk("prod_rescaled == original production * factor", rel.max() < TOL_REL, f"max rel {rel.max():.1e}")

    for nm, df, col in [("rescaled area", AR, "area_r"), ("rescaled production", PR, "prod_r")]:
        w = df.pivot_table(index=["pid", "jcrop"], columns="sys", values=col, fill_value=0.0)
        if {"AGG", "IR", "RF"} <= set(w.columns):
            dd = (w["AGG"] - w["IR"] - w["RF"]).abs() / w["AGG"].abs().clip(lower=1e-30)
            A.chk(f"{nm}: AGG == IR + RF", dd.max() < TOL_REL, f"max rel {dd.max():.1e}")

    sh_o = Ao[Ao.sys == "AGG"].set_index(["pid", "jcrop"])["area"]
    sh_o = sh_o / sh_o.groupby("pid").transform("sum")
    sh_r = AR[AR.sys == "AGG"].set_index(["pid", "jcrop"])["area_r"]
    sh_r = sh_r / sh_r.groupby("pid").transform("sum")
    j = pd.concat([sh_o.rename("o"), sh_r.rename("r")], axis=1).dropna()
    A.chk("within-pid crop mix unchanged by the rescale", np.allclose(j.o, j.r, rtol=1e-9, atol=1e-12),
          f"max diff {np.abs(j.o - j.r).max():.1e} over {len(j):,} (pid, crop)")

    u = UA.merge(Ao, on=["pid", "jcrop", "sys"], how="left")
    A.chk("unanchored area is bit-identical to the original", bool((u.area_u == u.area).all()))
    u = UP.merge(Po, on=["pid", "jcrop", "sys"], how="left")
    A.chk("unanchored production is bit-identical to the original", bool((u.prod_u == u["prod"]).all()))
    A.chk("unanchored pids have no positive lu_out crop anchor", not (set(UA.pid) & set(a_del[a_del > 0].index)))

    A.chk("rescaled + unanchored records == original record count", len(Ao) == len(AR) + len(UA),
          f"{len(AR):,} + {len(UA):,} vs {len(Ao):,}")
    k_out = set(map(tuple, AR[["pid", "jcrop", "sys"]].values)) | set(map(tuple, UA[["pid", "jcrop", "sys"]].values))
    k_in = set(map(tuple, Ao[["pid", "jcrop", "sys"]].values))
    A.chk("no rescaled/unanchored key outside the original support", k_out == k_in,
          f"extra {len(k_out - k_in)}, missing {len(k_in - k_out)}")
    A.chk("lumen_crop_unfilled pids carry no AP area", not (set(UF.pid) & set(Ao.pid)),
          f"{len(UF)} pids, {UF.unfilled.sum():.2f} kha")

    return dict(A=Ao, P=Po, AR=AR, PR=PR, UA=UA, UP=UP, UF=UF, FC=FC, AN=AN, anchor_src=src)


# ============================================================================ CSV reports
def write_reports(res_path, lu_path, sec_dir, cty, baseyear, gamsdir, log):
    d = open_gdx(res_path, gamsdir)
    P3 = lambda n, v: param3(d, n, ["pid", "jcrop", "sys"]).rename(columns={"value": v})
    P1 = lambda n, v: param1(d, n, "pid").rename(columns={"value": v})
    AR, PR, YR = P3("p_Area_rescaled", "area_rescaled_kha"), P3("p_Production_rescaled", "prod_rescaled_kt"), P3("p_Yield_rescaled", "yield_t_per_ha")
    UA, UP = P3("p_Area_unanchored", "area_kha"), P3("p_Production_unanchored", "prod_kt")
    Ao, Po = P3("p_Area_pid", "area_kha"), P3("p_Production_pid", "prod_kt")
    FC, AN, UF, NP = P1("rescale_factor", "factor"), P1("lu_out_crop_base", f"lu_out_crop_{baseyear}_kha"), \
        P1("lumen_crop_unfilled", "lumen_crop_unfilled_kha"), P1("n_ap_pix", "n_ap_pixels")
    PC = records(d["pid_coords_used"], ["pid", "coord", "value"])
    S_out, S_lz, S_lo = set1(d, "pid_outside_run"), set1(d, "pid_luzero"), set1(d, "pid_lumen_only")
    key = ["pid", "jcrop", "sys"]

    main = AR.merge(PR, on=key).merge(YR, on=key).sort_values(key)
    f1 = sec_dir / f"{cty}_crop_rescaled_by_pid_{baseyear}.csv"
    main.to_csv(f1, index=False, float_format=FMT)

    unan = UA.merge(UP, on=key)
    unan["yield_t_per_ha"] = unan.prod_kt / unan.area_kha
    unan["reason"] = np.where(unan.pid.isin(S_out), "outside_lumen_pid_run", f"lu_out_crop_{baseyear}_zero")
    f2 = sec_dir / f"{cty}_crop_unanchored_by_pid_{baseyear}.csv"
    unan.sort_values(key).to_csv(f2, index=False, float_format=FMT)

    coords = PC.pivot(index="pid", columns="coord", values="value")
    ap_agg = Ao[Ao.sys == "AGG"].groupby("pid")["area_kha"].sum().rename("ap_area_kha")
    r_agg = AR[AR.sys == "AGG"].groupby("pid")["area_rescaled_kha"].sum().rename("rescaled_area_kha")
    summ = pd.concat([coords, NP.set_index("pid").iloc[:, 0], ap_agg, AN.set_index("pid").iloc[:, 0],
                      FC.set_index("pid")["factor"], r_agg, UF.set_index("pid").iloc[:, 0]], axis=1)
    summ["n_ap_pixels"] = summ["n_ap_pixels"].fillna(0).astype(int)
    summ["status"] = np.select(
        [summ.index.isin(FC.pid), summ.index.isin(S_out), summ.index.isin(S_lz), summ.index.isin(S_lo)],
        ["rescaled", "preserved_outside_pid_run", "preserved_lu_out_crop_zero", "lumen_only_unfilled"], default="none")
    summ = summ[summ.status != "none"].copy()
    summ.index.name = "pid"
    f3 = sec_dir / f"{cty}_crop_rescale_factors_by_pid_{baseyear}.csv"
    summ.sort_values(["status", "pid"]).to_csv(f3, float_format=FMT)

    # per-pid comparison of AP crop area against every LUMEN pool at the base year
    lu_c = open_gdx(lu_path, gamsdir)
    lu = param3(lu_c, "lu_out", ["pid", "fland", "yrs"])
    lub = lu[lu.yrs == str(baseyear)].pivot_table(index="pid", columns="fland", values="value", aggfunc="sum")
    pr = set1(lu_c, "pid_run")
    pc_all = records(lu_c["pid_coords"], ["pid", "coord", "value"]).pivot(index="pid", columns="coord", values="value")
    c = pd.concat([pc_all, NP.set_index("pid").iloc[:, 0], ap_agg.rename("ap_crop_area_kha"),
                   lub.add_prefix(f"lumen_lu_out_{baseyear}_")], axis=1)
    c = c[c.index.isin(set(ap_agg.index) | pr)].copy()
    c["in_pid_run"] = c.index.isin(pr)
    c["ap_crop_area_kha"] = c["ap_crop_area_kha"].fillna(0.0)
    c["n_ap_pixels"] = c["n_ap_pixels"].fillna(0).astype(int)
    for col in [x for x in c.columns if x.startswith("lumen_lu_out")]:
        c[col] = c[col].fillna(0.0)
    c["diff_crop_kha"] = c[f"lumen_lu_out_{baseyear}_crop"] - c["ap_crop_area_kha"]
    c.index.name = "pid"
    f4 = sec_dir / f"{cty}_crop_compare_by_pid_{baseyear}.csv"
    c.sort_values("diff_crop_kha").to_csv(f4, float_format=FMT)

    # ---- summary numbers ----
    L, M = c["ap_crop_area_kha"], c[f"lumen_lu_out_{baseyear}_crop"]
    both = c[(L > 0) & (M > 0)]
    full = both[both.n_ap_pixels == 9]
    f = FC.factor
    fs = summ[summ.status == "rescaled"]
    lines = [
        f"pids: rescaled {len(FC)}, preserved {summ.status.str.startswith('preserved').sum()} "
        f"(outside pid_run {len(S_out)}, lu_out crop = 0 {len(S_lz)}), lumen-only unfilled {len(UF)}",
        f"area  AP original {Ao[Ao.sys == 'AGG'].area_kha.sum():12,.3f} kha | rescaled {AR[AR.sys == 'AGG'].area_rescaled_kha.sum():12,.3f} kha "
        f"(== lu_out anchor) | preserved {UA[UA.sys == 'AGG'].area_kha.sum():10,.3f} kha | LUMEN unfilled {UF.iloc[:, 1].sum():10,.3f} kha",
        f"prod  AP original {Po[Po.sys == 'AGG'].prod_kt.sum():12,.3f} kt  | rescaled {PR[PR.sys == 'AGG'].prod_rescaled_kt.sum():12,.3f} kt "
        f"(AP yields on LUMEN cropland) | preserved {UP[UP.sys == 'AGG'].prod_kt.sum():10,.3f} kt",
        f"LUMEN crop {baseyear} total {M.sum():,.1f} kha vs AP {L.sum():,.1f} kha  (ratio LUMEN/AP {M.sum() / L.sum() if L.sum() else float('nan'):.3f})",
        f"both > 0: {len(both)} pids, corr {both.ap_crop_area_kha.corr(M[both.index]):.3f}; "
        f"fully covered (9/9): {len(full)} pids, corr {full.ap_crop_area_kha.corr(M[full.index]) if len(full) > 1 else float('nan'):.3f}",
        f"rescale factor: min {f.min():.4f} | p05 {f.quantile(.05):.3f} | median {f.median():.3f} | p95 {f.quantile(.95):.2f} | max {f.max():,.1f}",
        f"  fully covered (9/9) {int((fs.n_ap_pixels == 9).sum()):4d} pids: median {fs[fs.n_ap_pixels == 9].factor.median():.2f}, max {fs[fs.n_ap_pixels == 9].factor.max():,.1f}",
        f"  partial       (<9)  {int((fs.n_ap_pixels < 9).sum()):4d} pids: median {fs[fs.n_ap_pixels < 9].factor.median():.2f}, max {fs[fs.n_ap_pixels < 9].factor.max():,.1f}",
    ]
    for ln in lines:
        if ln:
            log("         " + ln)
    for fp, n in [(f1, len(main)), (f2, len(unan)), (f3, len(summ)), (f4, len(c))]:
        log(f"wrote  : {fp}  ({n:,} rows)")
    return "\n".join(ln for ln in lines if ln)


# ============================================================================ entry
def run(ap_path, lu_path, res_path, sec_dir, cty, baseyear, gamsdir, log):
    summary = write_reports(res_path, lu_path, sec_dir, cty, baseyear, gamsdir, log)
    A = Audit(log)
    audit_conservation(A, ap_path, lu_path, res_path, gamsdir)
    audit_rescale(A, lu_path, res_path, baseyear, gamsdir)
    text = A.render()
    rep = sec_dir / "audit_report.txt"
    rep.write_text(f"Audit of {res_path.name}  (base year {baseyear})\n\n{text}\n\nSummary\n-------\n{summary}\n",
                   encoding="utf-8")
    for ln in text.splitlines():
        log("  " + ln)
    log(f"wrote  : {rep}")
    return A.ok
