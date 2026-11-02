"""Step 1 - crosswalk the AP 5-arcmin grid onto the LUMEN 0.25-degree pid grid and
aggregate AP's per-pixel crop area and production onto that grid.

Inputs
  solution_lu.gdx   LUMEN: pid, pid_coords, pid_run, cty_run, yrs
  PIXEL_TO_DIM.gdx  AP master grid: every 5-arcmin pixel key -> (X, Y) centre
  AP_<cty>...gdx    AP downscale: PIXEL_TO_DIM (its own pixels), p_Area, p_Production

Outputs
  output/pixel5min_to_pid025.gdx                  the general, global crosswalk
  output/secondary/<cty>_crop_in_pid_coords.gdx   AP's crop data on the pid grid
  output/secondary/crosswalk_*.csv                the same, for inspection

Geometry (see docs/): both grids are cell-centre grids on the same origin and
0.25 deg = 3 x (1/12 deg), so 9 AP pixels nest exactly in one LUMEN pid.
  i24 = round(X*24)   -> odd integer           (AP centre at (2k+1)/24)
  m   = floor(i24/6)  -> index of the 0.25 cell (floor toward -inf, NOT truncation)
  k8  = 2m+1          -> LUMEN centre at k8/8   (LUMEN centre at (2m+1)/8)
"""
import numpy as np
import pandas as pd
import gams.transfer as gt

from gdxio import PipelineError, open_gdx, new_gdx, records, param3, long_coords


# ----------------------------------------------------------------------------- geometry
def read_pixel_dim(c, name="PIXEL_TO_DIM"):
    """AP's pixel table (a Set in the country file, a Parameter in the master) -> pixel,x,y."""
    if name not in c.listSymbols():
        raise PipelineError(f"symbol {name} not found; symbols are {c.listSymbols()}")
    df = records(c[name], ["pixel", "x", "y"])
    df["x"] = df["x"].astype(float)
    df["y"] = df["y"].astype(float)
    if df.pixel.duplicated().any():
        raise PipelineError(f"{name}: duplicate pixel keys")
    return df


def ap_cell_key(coord, label):
    """5-arcmin centre coordinate -> odd integer k8 such that the containing 0.25-deg cell
    has its centre at k8/8. Fails loudly if the coordinates are not on a (2k+1)/24 grid."""
    coord = np.asarray(coord, dtype=float)
    k24 = coord * 24.0
    i24 = np.rint(k24).astype(np.int64)
    dev = np.abs(k24 - i24).max() if len(coord) else 0.0
    if dev > 0.05:  # label rounding gives ~1e-3; anything bigger is a different grid
        raise PipelineError(f"AP {label}: coordinates are not on the 5-arcmin centre grid "
                            f"(max |coord*24 - int| = {dev:.3g})")
    if not np.all(i24 % 2 != 0):
        raise PipelineError(f"AP {label}: coord*24 is not always odd - not a cell-centre grid")
    return 2 * np.floor_divide(i24, 6) + 1


def lumen_cell_key(coord, label):
    coord = np.asarray(coord, dtype=float)
    k8 = coord * 8.0
    i8 = np.rint(k8).astype(np.int64)
    dev = np.abs(k8 - i8).max() if len(coord) else 0.0
    if dev > 1e-6:
        raise PipelineError(f"LUMEN {label}: coordinates are not on the 0.25-deg centre grid "
                            f"(max |coord*8 - int| = {dev:.3g})")
    if not np.all(i8 % 2 != 0):
        raise PipelineError(f"LUMEN {label}: coord*8 is not always odd - not a cell-centre grid")
    return i8


# ----------------------------------------------------------------------------- LUMEN
def read_lumen(lu_path, gamsdir, log):
    c = open_gdx(lu_path, gamsdir)
    pids = records(c["pid"], ["pid"]).pid.tolist()
    pc = records(c["pid_coords"], ["pid", "coord", "value"])
    pc = pc.pivot(index="pid", columns="coord", values="value")
    pc = pc.reindex(pids).reset_index()
    if pc[["x", "y"]].isna().any().any():
        raise PipelineError("solution_lu: some pids have no coordinates in pid_coords")
    pc["kx"] = lumen_cell_key(pc.x, "x")
    pc["ky"] = lumen_cell_key(pc.y, "y")
    if pc.duplicated(["kx", "ky"]).any():
        raise PipelineError("solution_lu: two pids share the same cell centre")
    pid_run = set(records(c["pid_run"], ["pid"]).pid)
    cty_run = sorted(records(c["cty_run"], ["cty"]).cty) if "cty_run" in c.listSymbols() else []
    yrs = sorted(records(c["yrs"], ["yrs"]).yrs, key=lambda s: int(s))
    log(f"LUMEN  : {len(pids):,} pids in land mask, {len(pid_run):,} in pid_run, "
        f"cty_run = {cty_run}, years {yrs[0]}-{yrs[-1]}")
    return dict(pids=pids, pidtab=pc, pid_run=pid_run, cty_run=cty_run, yrs=yrs)


# ----------------------------------------------------------------------------- crosswalk
def build_crosswalk(pixel_path, lumen, gamsdir, log):
    """Every pixel in the master PIXEL_TO_DIM -> the LUMEN pid containing it (or none)."""
    c = open_gdx(pixel_path, gamsdir)
    px = read_pixel_dim(c)
    px["kx"] = ap_cell_key(px.x, "X")
    px["ky"] = ap_cell_key(px.y, "Y")
    xw = px.merge(lumen["pidtab"][["kx", "ky", "pid"]], on=["kx", "ky"], how="left")
    xw["cell_x"] = xw.kx / 8.0
    xw["cell_y"] = xw.ky / 8.0
    # the SPAM-grid decode of the key is an independent check of the stored coordinates
    key = xw.pixel.astype(np.int64).values
    lon = -180.0 + ((key % 4320) + 0.5) / 12.0
    lat = 90.0 - ((key // 4320) + 0.5) / 12.0
    d = max(np.abs(lon - xw.x).max(), np.abs(lat - xw.y).max())
    if d > 0.01:
        raise PipelineError(f"master PIXEL_TO_DIM: key does not decode to the stored coords "
                            f"(max diff {d:.3g} deg)")
    n_map = xw.pid.notna().sum()
    log(f"MASTER : {len(xw):,} AP pixels -> {n_map:,} mapped to a pid, "
        f"{len(xw) - n_map:,} fall in cells outside the LUMEN land mask "
        f"(key decodes as SPAM 4320x2160 grid, max dev {d:.1e} deg)")
    return xw


def write_crosswalk_gdx(xw, lumen, path, gamsdir):
    m = new_gdx(gamsdir)
    s_pix = gt.Set(m, "PIXEL_S", records=xw.pixel.tolist(),
                   description="AP 5-arcmin pixel keys (row*4320+col on the global SPAM grid)")
    s_pid = gt.Set(m, "pid", records=lumen["pids"], description="LUMEN 0.25-deg pixel IDs")
    s_co = gt.Set(m, "coord", records=["x", "y"], description="coordinate")
    mapped = xw.pid.notna()
    gt.Set(m, "PIXEL_TO_PID", domain=[s_pix, s_pid], records=xw.loc[mapped, ["pixel", "pid"]],
           description="each AP 5-arcmin pixel -> the LUMEN 0.25-deg pid containing it (9:1 nesting)")
    nop = xw.loc[~mapped, ["pixel"]]
    gt.Set(m, "PIXEL_NOPID", domain=[s_pix], records=None if nop.empty else nop,
           description="AP pixels whose 0.25-deg cell is not in the LUMEN land mask")
    gt.Parameter(m, "pixel_coords", domain=[s_pix, s_co], records=long_coords(xw, "pixel"),
                 description="AP pixel cell-centre coordinates (deg)")
    gt.Parameter(m, "pid_coords", domain=[s_pid, s_co],
                 records=long_coords(lumen["pidtab"], "pid"),
                 description="LUMEN pid cell-centre coordinates (deg)")
    m.write(str(path), compress=True)


# ----------------------------------------------------------------------------- AP -> pid
def map_ap(ap_path, xw, lumen, gamsdir, log):
    c = open_gdx(ap_path, gamsdir)
    ap = read_pixel_dim(c)
    ap["kx"] = ap_cell_key(ap.x, "X")
    ap["ky"] = ap_cell_key(ap.y, "Y")
    ap = ap.merge(lumen["pidtab"][["kx", "ky", "pid"]], on=["kx", "ky"], how="left")
    ap["cell_x"] = ap.kx / 8.0
    ap["cell_y"] = ap.ky / 8.0

    # cross-check against the master crosswalk: same key must give same coords and same pid
    chk = ap.merge(xw[["pixel", "x", "y", "pid"]], on="pixel", how="left", suffixes=("", "_m"))
    in_master = chk.x_m.notna()
    if in_master.any():
        dc = max(np.abs(chk.x - chk.x_m)[in_master].max(), np.abs(chk.y - chk.y_m)[in_master].max())
        if dc > 1e-3:
            raise PipelineError(f"AP file coords disagree with master PIXEL_TO_DIM (max {dc:.3g} deg)")
        bad = in_master & (chk.pid.fillna("-") != chk.pid_m.fillna("-"))
        if bad.any():
            raise PipelineError(f"{bad.sum()} AP pixels map to a different pid than the master "
                                f"crosswalk, e.g. {chk.loc[bad, ['pixel', 'pid', 'pid_m']].head().to_dict('records')}")
    n_out = (~in_master).sum()
    log(f"AP     : {len(ap):,} pixels, {ap.pid.notna().sum():,} mapped to a pid, "
        f"{ap.pid.isna().sum():,} with no pid in the LUMEN land mask; "
        f"{in_master.sum():,} are in the master grid (coords and pid agree), {n_out:,} are not")

    area = param3(c, "p_Area", ["pixel", "jcrop", "sys"]).rename(columns={"value": "area"})
    prod = param3(c, "p_Production", ["pixel", "jcrop", "sys"]).rename(columns={"value": "prod"})
    jcrop = list(c["p_Area"].records.iloc[:, 1].cat.categories)
    sys_ = list(c["p_Area"].records.iloc[:, 2].cat.categories)
    d = area.merge(prod, on=["pixel", "jcrop", "sys"], how="outer")
    missing = set(d.pixel) - set(ap.pixel)
    if missing:
        raise PipelineError(f"{len(missing)} AP pixels carry data but have no coordinates in "
                            f"the AP file's PIXEL_TO_DIM, e.g. {sorted(missing)[:5]}")
    d = d.merge(ap[["pixel", "pid"]], on="pixel", how="left")
    d[["area", "prod"]] = d[["area", "prod"]].fillna(0.0)

    agg = (d.dropna(subset=["pid"]).groupby(["pid", "jcrop", "sys"], as_index=False)[["area", "prod"]].sum())
    resid = d[d.pid.isna()][["pixel", "jcrop", "sys", "area", "prod"]].copy()
    n_ap_pix = ap.dropna(subset=["pid"]).groupby("pid").size().rename("n_ap_pix")
    pid_used = sorted(agg.loc[agg.area.abs() > 0, "pid"].unique(), key=lambda s: int(s[1:]))

    for v, lab in [("area", "area (1000 ha)"), ("prod", "production (1000 t)")]:
        ti = d.loc[d.sys == "AGG", v].sum()
        to = agg.loc[agg.sys == "AGG", v].sum()
        log(f"         AGG {lab:20s} in = {ti:14,.4f}   on pid grid = {to:14,.4f}   "
            f"residual (no pid) = {ti - to:,.4f} ({100 * (ti - to) / ti if ti else 0:.4f}%)")
    log(f"         {len(d):,} pixel-crop-sys records -> {len(agg):,} pid-crop-sys records on "
        f"{len(pid_used):,} pids; {len(resid):,} residual records on {resid.pixel.nunique()} unmapped pixels")
    return dict(ap=ap, agg=agg, resid=resid, n_ap_pix=n_ap_pix, pid_used=pid_used,
                jcrop=jcrop, sys=sys_)


def write_crop_gdx(r, lumen, path, gamsdir):
    m = new_gdx(gamsdir)
    s_pid = gt.Set(m, "pid", records=lumen["pids"], description="LUMEN 0.25-deg pixel IDs")
    s_pix = gt.Set(m, "PIXEL_S", records=r["ap"].pixel.tolist(),
                   description="AP 5-arcmin pixel keys in this downscale file")
    s_j = gt.Set(m, "JCROP", records=r["jcrop"], description="crops (IMPACT j-codes)")
    s_s = gt.Set(m, "SYS", records=r["sys"], description="production system")
    s_co = gt.Set(m, "coord", records=["x", "y"], description="coordinate")
    gt.Set(m, "pid_used", domain=[s_pid], records=r["pid_used"],
           description="LUMEN pids carrying AP crop area")
    un = r["resid"].pixel.drop_duplicates().tolist()
    s_un = gt.Set(m, "PIXEL_UNMAPPED", domain=[s_pix], records=un or None,
                  description="AP pixels with no matching pid in the LUMEN land mask")
    mp = r["ap"].dropna(subset=["pid"])[["pixel", "pid"]]
    gt.Set(m, "PIXEL_TO_PID_AP", domain=[s_pix, s_pid], records=mp,
           description="AP pixels of this file -> the LUMEN pid containing them")
    pc = lumen["pidtab"][lumen["pidtab"].pid.isin(r["pid_used"])]
    gt.Parameter(m, "pid_coords_used", domain=[s_pid, s_co], records=long_coords(pc, "pid"),
                 description="cell-centre coords of the LUMEN pids carrying AP crop area (deg)")
    gt.Parameter(m, "n_ap_pix", domain=[s_pid], records=r["n_ap_pix"].reset_index(),
                 description="number of AP 5-arcmin pixels contributing to this pid (9 = fully covered)")
    agg = r["agg"]
    gt.Parameter(m, "p_Area_pid", domain=[s_pid, s_j, s_s], records=agg[["pid", "jcrop", "sys", "area"]],
                 description="AP crop area summed to the LUMEN pid grid (1000 ha)")
    gt.Parameter(m, "p_Production_pid", domain=[s_pid, s_j, s_s], records=agg[["pid", "jcrop", "sys", "prod"]],
                 description="AP crop production summed to the LUMEN pid grid (1000 t)")
    res = r["resid"]
    gt.Parameter(m, "p_Area_unmapped", domain=[s_un, s_j, s_s],
                 records=None if res.empty else res[["pixel", "jcrop", "sys", "area"]],
                 description="AP area on pixels with no pid in the LUMEN land mask (1000 ha)")
    gt.Parameter(m, "p_Production_unmapped", domain=[s_un, s_j, s_s],
                 records=None if res.empty else res[["pixel", "jcrop", "sys", "prod"]],
                 description="AP production on pixels with no pid in the LUMEN land mask (1000 t)")
    m.write(str(path))


# ----------------------------------------------------------------------------- entry
def run(lu_path, pixel_path, ap_path, out_dir, sec_dir, gamsdir, log):
    lumen = read_lumen(lu_path, gamsdir, log)
    cty = "_".join(lumen["cty_run"]) if lumen["cty_run"] else "ALL"

    xw = build_crosswalk(pixel_path, lumen, gamsdir, log)
    xw_gdx = out_dir / "pixel5min_to_pid025.gdx"
    write_crosswalk_gdx(xw, lumen, xw_gdx, gamsdir)
    xw.rename(columns={"pixel": "pixel_s", "x": "pixel_x", "y": "pixel_y"})[
        ["pixel_s", "pixel_x", "pixel_y", "cell_x", "cell_y", "pid"]
    ].to_csv(sec_dir / "crosswalk_pixel5min_to_pid025.csv", index=False)
    log(f"wrote  : {xw_gdx}")

    r = map_ap(ap_path, xw, lumen, gamsdir, log)
    crop_gdx = sec_dir / f"{cty}_crop_in_pid_coords.gdx"
    write_crop_gdx(r, lumen, crop_gdx, gamsdir)
    r["ap"].rename(columns={"pixel": "pixel_s", "x": "pixel_x", "y": "pixel_y"})[
        ["pixel_s", "pixel_x", "pixel_y", "cell_x", "cell_y", "pid"]
    ].to_csv(sec_dir / f"crosswalk_{cty}_pixels.csv", index=False)
    log(f"wrote  : {crop_gdx}")
    return dict(cty=cty, yrs=lumen["yrs"], crop_gdx=crop_gdx, crosswalk_gdx=xw_gdx)
