@echo off
REM ===========================================================================
REM  3_ADMIN.bat  -  BANK STAFF ONLY
REM
REM  The cardholder administration menu: list, add, edit a balance,
REM  lock / unlock, delete, and view recent transactions.
REM
REM  It works whether or not the bank is running, because it edits the
REM  database file directly.
REM ===========================================================================

title AAST Bank - Cardholder Admin
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
    goto got_python
)
where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py"
    goto got_python
)
set "PY=python"
:got_python

%PY% admin_cli.py

echo.
pause
