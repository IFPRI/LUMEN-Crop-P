"""LUMEN-Crop driver: AP 5-arcmin crop downscale -> LUMEN 0.25-deg pid grid -> rescaled to lu_out.

Usage (from the project root, normally via run.bat):
  python src/run.py [--ap input/AP_xxx.gdx] [--lu input/solution_lu.gdx]
                    [--pixel input/PIXEL_TO_DIM.gdx] [--baseyear 2021] [--gamsdir C:\\GAMS\\49]

Runs three steps and stops at the first failure:
  1  src/step1_crosswalk.py      crosswalk + aggregation   (Python, gams.transfer)
  2  src/step2_rescale.gms       rescale to lu_out          (GAMS)
  3  src/step3_report_audit.py   CSV reports + two audits   (Python)

Deliverables land in output/, everything else in output/secondary/.
"""
import argparse
import datetime as dt
import pathlib
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


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ap", default="input/AP_KEN_downscale_for_ABHI.gdx", help="AP downscale GDX (PIXEL_TO_DIM, p_Area, p_Production)")
    p.add_argument("--lu", default="input/solution_lu.gdx", help="LUMEN solution GDX (pid, pid_coords, pid_run, cty_run, lu_out)")
    p.add_argument("--pixel", default="input/PIXEL_TO_DIM.gdx", help="AP master 5-arcmin grid")
    p.add_argument("--baseyear", default=None, help="LUMEN year used as the rescale anchor; default = first year in solution_lu")
    p.add_argument("--gamsdir", default=None, help="GAMS system directory; default = the GAMS this Python ships with, else C:\\GAMS\\49")
    a = p.parse_args()

    gamsdir = pathlib.Path(a.gamsdir) if a.gamsdir else (
        pathlib.Path(sys.executable).parents[1] if pathlib.Path(sys.executable).parent.name == "GMSPython"
        else pathlib.Path(r"C:\GAMS\49"))
    gams_exe = gamsdir / "gams.exe"
    paths = {k: (ROOT / v if not pathlib.Path(v).is_absolute() else pathlib.Path(v)) for k, v in
             [("ap", a.ap), ("lu", a.lu), ("pixel", a.pixel)]}

    out = ROOT / "output"
    sec = out / "secondary"
    sec.mkdir(parents=True, exist_ok=True)
    log = Log(sec / "run_log.txt")
    t0 = time.time()
    log(f"LUMEN-Crop run  {dt.datetime.now():%Y-%m-%d %H:%M}")
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
        log("STEP 1 : crosswalk AP 5-arcmin pixels to LUMEN pids and aggregate AP crop data")
        import step1_crosswalk as s1
        info = s1.run(paths["lu"], paths["pixel"], paths["ap"], out, sec, gamsdir, log)
        cty = info["cty"]
        baseyear = a.baseyear or info["yrs"][0]
        if str(baseyear) not in info["yrs"]:
            raise PipelineError(f"base year {baseyear} is not in solution_lu yrs ({info['yrs'][0]}-{info['yrs'][-1]})")
        log(f"         country code {cty} (from cty_run), base year {baseyear}"
            + ("  (default: first year in solution_lu)" if not a.baseyear else "  (from --baseyear)"))

        # ---------------- step 2
        log()
        log(f"STEP 2 : rescale to lu_out(pid,'crop','{baseyear}')  [GAMS]")
        rescaled = out / f"{cty}_crop_in_pid_coords_rescaled.gdx"
        lst = sec / "step2_rescale.lst"
        cmd = [str(gams_exe), str(ROOT / "src" / "step2_rescale.gms"),
               f"--LU={paths['lu']}", f"--CROP={info['crop_gdx']}", f"--OUT={rescaled}",
               f"--BASEYEAR={baseyear}", f"o={lst}", "lo=0", f"curdir={sec}"]
        rc = subprocess.run(cmd, cwd=str(sec)).returncode
        if rc != 0 or not rescaled.exists():
            txt = lst.read_text(errors="replace") if lst.exists() else "(no listing)"
            tail = "\n".join(txt.splitlines()[-40:])
            raise PipelineError(f"GAMS rescale failed (return code {rc}). Listing tail:\n{tail}")
        # echo the in-build check scalars (the display block in the listing)
        block = False
        for line in lst.read_text(errors="replace").splitlines():
            if line.startswith("----") and "PARAMETER base_year" in line:
                block = True
            if block:
                if not line.strip():
                    break
                log("         " + line.split("PARAMETER", 1)[-1].strip() if "PARAMETER" in line else "         " + line.strip())
        log(f"wrote  : {rescaled}")

        # ---------------- step 3
        log()
        log("STEP 3 : CSV reports and audits")
        import step3_report_audit as s3
        ok = s3.run(paths["ap"], paths["lu"], rescaled, sec, cty, baseyear, gamsdir, log)
        if not ok:
            raise PipelineError("audit failed - see output/secondary/audit_report.txt")

    except PipelineError as e:
        log()
        log(f"FAILED : {e}")
        return 1

    log()
    log(f"DONE in {time.time() - t0:.0f} s")
    log(f"deliverables : {out / 'pixel5min_to_pid025.gdx'}")
    log(f"               {rescaled}")
    log(f"secondary    : {sec}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
