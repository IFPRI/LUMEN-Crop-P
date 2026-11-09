"""LUMEN-Crop driver: AP 5-arcmin crop downscale -> LUMEN 0.25-deg pid grid -> balanced to
lu_out per pid and to IMPACT AREACTYX0 per crop and system.

Usage (from the project root, normally via run.bat):
  python src/run.py [--ap input/AP_xxx.gdx] [--lu input/solution_lu.gdx] [--impact <IMPACT scenario gdx>]
                    [--pixel input/PIXEL_TO_DIM.gdx] [--baseyear 2021] [--gamsdir C:\\GAMS\\49] [--fresh]

Runs five steps and stops at the first failure:
  1  src/step1_crosswalk.py      crosswalk + aggregation + IMPACT targets (Python, gams.transfer)
  2  src/step2_balance.gms       RAS balance to lu_out rows and AREACTYX0 columns (GAMS)
  3  src/step3_report_audit.py   CSV reports + audits against the source files (Python)
  4  src/step4_totals.gms        country crop totals, yields and land totals at every stage -> totals GDX (GAMS)
  5  src/step5_handoff.gms       one GDX for the Crop Allocation Model (GAMS)

Deliverables land in output/, everything else in output/secondary/.
"""
import argparse
import datetime as dt
import pathlib
import re
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gdxio import PipelineError  # noqa: E402


class Log:
    def __init__(self, path):
        self.f = open(path, "w", encoding="utf-8")

    def __call__(self, msg=""):
        print(msg, flush=True)
        self.f.write(msg + "\n")
        self.f.flush()


def run_gams(gams_exe, gms, pf, pf_lines, lst, sec, log, echo_from, step):
    """Run a GAMS script with its arguments in a parameter file and echo its display blocks.

    Paths may contain spaces. GAMS wants key="value" (quotes around the value only), which a
    subprocess argument list cannot produce, so the arguments go in a parameter file and the
    command line is built as one string. Echoing starts at the first display block whose
    header contains echo_from and stops at the end of the execution output.
    """
    pf.write_text("\n".join(pf_lines + [f'o="{lst}"', "lo=0", f'curdir="{sec}"']) + "\n", encoding="utf-8")
    cmd = f'"{gams_exe}" "{gms}" pf="{pf}"'
    rc = subprocess.run(cmd, cwd=str(sec)).returncode
    if rc != 0:
        txt = lst.read_text(errors="replace") if lst.exists() else "(no listing)"
        tail = "\n".join(txt.splitlines()[-40:])
        raise PipelineError(f"GAMS {step} failed (return code {rc}). Listing tail:\n{tail}")
    block = False
    for line in lst.read_text(errors="replace").splitlines():
        if line.startswith("----") and echo_from in line:
            block = True
        if line.startswith(("EXECUTION TIME", "USER:", "**** FILE SUMMARY")):
            block = False
        if block and line.strip():
            log("         " + (re.sub(r"^----\s+\d+\s+", "", line).strip() if line.startswith("----") else line.strip()))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ap", default="input/AP_KEN_downscale_for_ABHI.gdx", help="AP downscale GDX (PIXEL_TO_DIM, p_Area, p_Production)")
    p.add_argument("--lu", default="input/solution_lu.gdx", help="LUMEN solution GDX (pid, pid_coords, pid_run, cty_run, lu_out)")
    p.add_argument("--pixel", default="input/PIXEL_TO_DIM.gdx", help="AP master 5-arcmin grid")
    p.add_argument("--impact", default="input/impact_scenario.gdx",
                   help="IMPACT scenario GDX the LUMEN run was driven by (AREACTYX0, CROPINTENSX0, LANDX0, YLDCTYX0)")
    p.add_argument("--baseyear", default=None, help="LUMEN year used as the rescale anchor; default = first year in solution_lu")
    p.add_argument("--gamsdir", default=None, help="GAMS system directory; default = the GAMS this Python ships with, else C:\\GAMS\\49")
    p.add_argument("--fresh", action="store_true", help="delete everything in output/ before running, so no stale file from an earlier run survives")
    a = p.parse_args()

    gamsdir = pathlib.Path(a.gamsdir) if a.gamsdir else (
        pathlib.Path(sys.executable).parents[1] if pathlib.Path(sys.executable).parent.name == "GMSPython"
        else pathlib.Path(r"C:\GAMS\49"))
    gams_exe = gamsdir / "gams.exe"
    paths = {k: (ROOT / v if not pathlib.Path(v).is_absolute() else pathlib.Path(v)) for k, v in
             [("ap", a.ap), ("lu", a.lu), ("pixel", a.pixel), ("impact", a.impact)]}

    out = ROOT / "output"
    sec = out / "secondary"
    n_removed, locked = 0, []
    if a.fresh and out.exists():
        # a file open in a GDX viewer or Excel cannot be deleted on Windows: report it and carry on,
        # the step that rewrites it will fail loudly if it is still locked then
        for f in sorted(out.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            try:
                if f.is_file():
                    f.unlink()
                    n_removed += 1
                elif f.is_dir():
                    f.rmdir()
            except OSError:
                locked.append(f)
    sec.mkdir(parents=True, exist_ok=True)
    log = Log(sec / "run_log.txt")
    t0 = time.time()
    log(f"LUMEN-Crop run  {dt.datetime.now():%Y-%m-%d %H:%M}")
    if a.fresh:
        log(f"fresh  : removed {n_removed} files from {out}")
        for f in locked:
            if f.is_file():
                log(f"WARNING: could not remove {f} (open in another program?) - it will be overwritten")
    log(f"GAMS   : {gamsdir}   Python {sys.version.split()[0]}")
    for k, v in paths.items():
        if not v.exists():
            log(f"ERROR  : input {k} not found: {v}")
            return 2
        log(f"input  : {k:6s} {v}  ({v.stat().st_size / 1e6:.1f} MB, modified {dt.datetime.fromtimestamp(v.stat().st_mtime):%Y-%m-%d})")
    if not gams_exe.exists():
        log(f"ERROR  : gams.exe not found in {gamsdir}")
        return 2

    try:
        # ---------------- step 1
        log()
        log("STEP 1 : crosswalk AP 5-arcmin pixels to LUMEN pids, aggregate AP crop data, extract IMPACT targets")
        import step1_crosswalk as s1
        info = s1.run(paths["lu"], paths["pixel"], paths["ap"], paths["impact"], out, sec, gamsdir, log)
        cty = info["cty"]
        baseyear = a.baseyear or info["yrs"][0]
        if str(baseyear) not in info["yrs"]:
            raise PipelineError(f"base year {baseyear} is not in solution_lu yrs ({info['yrs'][0]}-{info['yrs'][-1]})")
        log(f"         country code {cty} (from cty_run), base year {baseyear}"
            + ("  (default: first year in solution_lu)" if not a.baseyear else "  (from --baseyear)"))

        # ---------------- step 2
        log()
        log(f"STEP 2 : balance to lu_out(pid,'crop','{baseyear}') per pid and AREACTYX0 per crop  [GAMS, RAS]")
        rescaled = out / f"{cty}_crop_in_pid_coords_balanced.gdx"
        run_gams(gams_exe, ROOT / "src" / "step2_balance.gms", sec / "step2_balance.pf",
                 [f'--LU="{paths["lu"]}"', f'--CROP="{info["crop_gdx"]}"', f'--TARGETS="{info["targets_gdx"]}"',
                  f'--OUT="{rescaled}"', f"--BASEYEAR={baseyear}"],
                 sec / "step2_balance.lst", sec, log, echo_from="PARAMETER cty_lu_crop", step="balance")
        if not rescaled.exists():
            raise PipelineError(f"GAMS balance produced no output file {rescaled}")
        log(f"wrote  : {rescaled}")

        # ---------------- step 3
        log()
        log("STEP 3 : CSV reports and audits")
        import step3_report_audit as s3
        ok = s3.run(paths["ap"], paths["lu"], paths["impact"], rescaled, sec, cty, baseyear, gamsdir, log)
        if not ok:
            raise PipelineError("audit failed - see output/secondary/audit_report.txt")

        # ---------------- step 4
        log()
        log(f"STEP 4 : country crop totals, yields and land totals at every stage, base year {baseyear}  [GAMS]")
        totals_gdx = sec / f"{cty}_totals.gdx"
        run_gams(gams_exe, ROOT / "src" / "step4_totals.gms", sec / "step4_totals.pf",
                 [f'--AP="{paths["ap"]}"', f'--LU="{paths["lu"]}"', f'--CROP="{info["crop_gdx"]}"',
                  f'--TARGETS="{info["targets_gdx"]}"', f'--BAL="{rescaled}"', f'--OUT="{totals_gdx}"',
                  f"--BASEYEAR={baseyear}"],
                 sec / "step4_totals.lst", sec, log, echo_from="PARAMETER crop_tot", step="totals")
        if not totals_gdx.exists():
            raise PipelineError(f"GAMS totals produced no output file {totals_gdx}")
        log(f"wrote  : {totals_gdx}")
        log(f"listing: {sec / 'step4_totals.lst'}")

        # ---------------- step 5
        log()
        log(f"STEP 5 : one GDX for the Crop Allocation Model: balanced areas, yields, LUMEN cropland path, IMPACT targets, crosswalk  [GAMS]")
        handoff_gdx = out / f"{cty}_for_CropAllocation.gdx"
        run_gams(gams_exe, ROOT / "src" / "step5_handoff.gms", sec / "step5_handoff.pf",
                 [f'--LU="{paths["lu"]}"', f'--TARGETS="{info["targets_gdx"]}"', f'--BAL="{rescaled}"',
                  f'--OUT="{handoff_gdx}"', f"--BASEYEAR={baseyear}"],
                 sec / "step5_handoff.lst", sec, log, echo_from="PARAMETER base_year", step="hand-off")
        if not handoff_gdx.exists():
            raise PipelineError(f"GAMS hand-off produced no output file {handoff_gdx}")
        log(f"wrote  : {handoff_gdx}")

    except PipelineError as e:
        log()
        log(f"FAILED : {e}")
        return 1

    log()
    log(f"DONE in {time.time() - t0:.0f} s")
    log(f"deliverables : {out / 'pixel5min_to_pid025.gdx'}")
    log(f"               {rescaled}")
    log(f"               {handoff_gdx}   <- the one file for the Crop Allocation Model")
    log(f"secondary    : {sec}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
