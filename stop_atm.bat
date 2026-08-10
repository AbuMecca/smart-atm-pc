@echo off
REM ===========================================================================
REM  stop_atm.bat - closes the two windows that start_atm.bat opened.
REM
REM  You can always just click the X on the two black windows instead;
REM  this file is only here to make it one click.
REM ===========================================================================

title AAST Bank - Shutdown

echo ============================================================
echo   AAST Bank - Smart ATM - shutting down
echo ============================================================
echo.

echo Closing the Web Portal window...
taskkill /FI "WINDOWTITLE eq AAST Bank - Web Portal*" /T /F >nul 2>nul
if %errorlevel%==0 (echo   ... closed.) else (echo   ... was not running.)

echo Closing the Serial Listener window...
taskkill /FI "WINDOWTITLE eq AAST Bank - Serial Listener*" /T /F >nul 2>nul
if %errorlevel%==0 (echo   ... closed.) else (echo   ... was not running.)

echo.
echo Done. If a window is somehow still open, just close it with the X.
echo.
pause
