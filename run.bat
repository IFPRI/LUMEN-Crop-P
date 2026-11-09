@echo off
rem LUMEN-CAM: run the whole pipeline. Any arguments are passed to src\run.py, e.g.
rem   run.bat --impact <path to the IMPACT scenario gdx>
rem   run.bat                                   (if the IMPACT scenario is copied to input\impact_scenario.gdx;
rem                                              the AP file is found automatically if input\ holds one AP_*.gdx)
rem   run.bat --impact <scenario.gdx> --ap input\AP_UGA_downscale.gdx --baseyear 2021
rem   run.bat --fresh --impact <scenario.gdx>     (wipe output\ first so nothing stale survives)
rem   run.bat --help
setlocal
set GAMSDIR=C:\GAMS\49
if not exist "%GAMSDIR%\GMSPython\python.exe" (
  echo GAMS Python not found at %GAMSDIR%\GMSPython\python.exe - edit GAMSDIR in run.bat
  exit /b 2
)
cd /d "%~dp0"
"%GAMSDIR%\GMSPython\python.exe" "%~dp0src\run.py" --gamsdir "%GAMSDIR%" %*
exit /b %ERRORLEVEL%
