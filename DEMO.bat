@echo off
REM ===========================================================================
REM  DEMO.bat  -  the one file to double-click for the demo.
REM
REM  It starts:
REM    1. the website        (bank dashboard + the big /atm mirror screen)
REM    2. the serial listener in COM-PORT mode, talking to the STM32
REM  then opens the browser at the ATM mirror screen.
REM
REM  The COM port is set at the top of serial_listener.py (SERIAL_PORT).
REM  If the board is not plugged in, the listener drops into manual mode so
REM  you can type ST: lines by hand and still drive the screen.
REM
REM  Press F11 in the browser for full screen on the projector.
REM  Close everything with STOP.bat.
REM ===========================================================================

title AAST Bank - Demo Launcher
cd /d "%~dp0"

echo ============================================================
echo   AAST BANK  -  Smart ATM demo
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

REM --- Start the website ------------------------------------------------------
echo Starting the website...
start "AAST Bank - Website" cmd /k "%PY% app.py"

REM --- Start the link to the STM32 --------------------------------------------
echo Starting the STM32 serial listener...
start "AAST Bank - STM32 Link" cmd /k "%PY% serial_listener.py"

timeout /t 3 /nobreak >nul

REM --- Open the big ATM screen -------------------------------------------------
echo Opening the ATM mirror screen...
start "" "http://localhost:5000/atm"

echo.
echo ============================================================
echo   RUNNING.
echo.
echo   ATM screen (projector) . . http://localhost:5000/atm
echo                              press F11 for full screen
echo   Bank dashboard (staff) . . http://localhost:5000
echo.
echo   The "STM32 Link" window shows every line the board sends.
echo   No board connected? It switches to manual mode - type
echo   lines like  ST:WELCOME:Amro  or  ST:DISPENSE:500  there
echo   and watch the big screen change.
echo.
echo   Manage cardholders with ADMIN.bat.
echo   Shut everything down with STOP.bat.
echo ============================================================
echo.
pause
