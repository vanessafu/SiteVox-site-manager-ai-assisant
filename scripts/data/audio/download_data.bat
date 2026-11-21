@echo off
rem Doppelklick: laedt ASR-Testdaten nach data\raw (siehe download_data.py).
rem Nutzt die Projekt-venv, falls vorhanden; sonst das installierte Python.
setlocal
set "PYTHONUTF8=1"
set "ROOT=%~dp0..\..\.."
if exist "%ROOT%\.venv\Scripts\python.exe" (
  "%ROOT%\.venv\Scripts\python.exe" "%~dp0download_data.py" %*
) else (
  py -3 "%~dp0download_data.py" %* || python "%~dp0download_data.py" %*
)
echo.
pause
