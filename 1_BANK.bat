@echo off
REM ===========================================================================
REM  1_BANK.bat  -  START THIS FIRST
REM
REM  Runs the BANK side of the system:
REM    * the bank's website  (staff only)  -> http://localhost:5000
REM    * the bank's ATM link (waits for a cash machine to connect)
REM
REM  Leave the two windows it opens running. Then start 2_ATM.bat.
REM ===========================================================================

title AAST Bank - Bank Launcher
cd /d "%~dp0"

echo ============================================================
echo   AAST BANK  -  starting the BANK
echo ============================================================
echo.

REM --- Choose how to run Python --------------------------------------------
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
    goto got_python
)
where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py"
    goto got_python
)
where python >nul 2>nul
if %errorlevel%==0 (
    set "PY=python"
    goto got_python
)
echo   ERROR: Python was not found on this PC.
echo   Install it from https://www.python.org/downloads/
echo   and tick "Add python.exe to PATH".
echo.
pause
exit /b 1
:got_python

REM --- Libraries -------------------------------------------------------------
%PY% -c "import flask, serial" >nul 2>nul
if not %errorlevel%==0 (
    echo Installing the required libraries, please wait...
    %PY% -m pip install -r requirements.txt
)

REM --- Database --------------------------------------------------------------
if not exist "atm.db" (
    echo First run - creating atm.db with the sample accounts...
    %PY% seed.py
)

REM --- Start the two bank programs -------------------------------------------
echo Starting the bank website...
start "AAST Bank - Website"  cmd /k "%PY% app.py"

echo Starting the bank ATM link...
start "AAST Bank - ATM Link" cmd /k "%PY% serial_listener.py --listen"

timeout /t 3 /nobreak >nul

echo Opening the staff dashboard...
start "" "http://localhost:5000"

echo.
echo ============================================================
echo   THE BANK IS RUNNING.
echo.
echo   Staff dashboard . . http://localhost:5000
echo   (all accounts and live transactions - STAFF ONLY)
echo.
echo   NEXT: double-click  2_ATM.bat  to open a cash machine.
echo         double-click  3_ADMIN.bat  to manage cardholders.
echo.
echo   To shut everything down: run STOP.bat
echo ============================================================
echo.
pause
