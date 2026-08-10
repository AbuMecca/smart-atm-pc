@echo off
REM ===========================================================================
REM  start_atm.bat - brings the whole Smart ATM PC side up with one double-click
REM
REM  It will:
REM    1. move into this project folder (wherever you put it)
REM    2. use a .venv virtual environment if you made one, otherwise plain Python
REM    3. create atm.db with the sample accounts if it does not exist yet
REM    4. open the web portal in its own window
REM    5. open the serial listener in its own window
REM    6. open your browser at the dashboard
REM
REM  Close the two black windows (or run stop_atm.bat) to shut it all down.
REM ===========================================================================

title AAST Bank - Launcher

REM --- 1. Always work in the folder this .bat file lives in -----------------
cd /d "%~dp0"

echo ============================================================
echo   AAST Bank - Smart ATM - starting up
echo   Folder: %CD%
echo ============================================================
echo.

REM --- 2. Choose how to run Python -----------------------------------------
REM  Prefer a virtual environment if the project has one.
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
    echo [1/5] Using the virtual environment in .venv
    goto got_python
)

REM  Otherwise prefer the "py" launcher, which avoids the Microsoft Store
REM  fake python.exe that prints "Python was not found".
where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py"
    echo [1/5] Using the Windows Python launcher: py
    goto got_python
)

REM  Last resort: plain python.
where python >nul 2>nul
if %errorlevel%==0 (
    set "PY=python"
    echo [1/5] Using: python
    goto got_python
)

echo.
echo   ERROR: Python was not found on this PC.
echo.
echo   Install Python 3 from https://www.python.org/downloads/
echo   and tick "Add python.exe to PATH" during the install.
echo.
pause
exit /b 1

:got_python

REM --- 3. Check the libraries are installed --------------------------------
%PY% -c "import flask, serial" >nul 2>nul
if not %errorlevel%==0 (
    echo [2/5] Installing the required libraries, please wait...
    %PY% -m pip install -r requirements.txt
    if not %errorlevel%==0 (
        echo.
        echo   ERROR: could not install the libraries. Check your internet
        echo   connection, then run this file again.
        echo.
        pause
        exit /b 1
    )
) else (
    echo [2/5] Flask and pyserial are installed.
)

REM --- 4. Create the database on first run ---------------------------------
if not exist "atm.db" (
    echo [3/5] First run - creating atm.db with the sample accounts...
    %PY% seed.py
) else (
    echo [3/5] Using the existing atm.db.
)

REM --- 5. Start the two programs, each in its own window --------------------
echo [4/5] Starting the web portal and the serial listener...
start "AAST Bank - Web Portal"      cmd /k "%PY% app.py"
start "AAST Bank - Serial Listener" cmd /k "%PY% serial_listener.py"

REM  Give Flask a couple of seconds to bind port 5000 before the browser opens.
timeout /t 3 /nobreak >nul

REM --- 6. Open the dashboard ------------------------------------------------
echo [5/5] Opening http://localhost:5000 in your browser...
start "" "http://localhost:5000"

echo.
echo ============================================================
echo   Running.
echo.
echo   Dashboard . . . . http://localhost:5000
echo   Two windows opened: "Web Portal" and "Serial Listener".
echo.
echo   The Serial Listener tries the COM port set at the top of
echo   serial_listener.py. If no board is connected it switches
echo   to manual mode, where you can type protocol lines such as
echo   GET:A1B2C3D4 by hand to demo without the STM32.
echo.
echo   To stop everything: close those two windows, or run
echo   stop_atm.bat.
echo ============================================================
echo.
pause
