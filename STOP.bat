@echo off
REM ===========================================================================
REM  STOP.bat  -  closes everything this project opened.
REM
REM  You can also just close the windows by hand; this is only quicker.
REM ===========================================================================

title AAST Bank - Shutdown

echo ============================================================
echo   AAST BANK  -  shutting everything down
echo ============================================================
echo.

echo Closing the bank website...
taskkill /FI "WINDOWTITLE eq AAST Bank - Website*" /T /F >nul 2>nul
if %errorlevel%==0 (echo   ... closed.) else (echo   ... was not running.)

echo Closing the bank ATM link...
taskkill /FI "WINDOWTITLE eq AAST Bank - ATM Link*" /T /F >nul 2>nul
if %errorlevel%==0 (echo   ... closed.) else (echo   ... was not running.)

echo Closing any cash machines...
REM  Cash machines run under pythonw.exe. taskkill reports a non-zero code
REM  both when none were running and when some were, so we do not try to
REM  guess which happened - we just say what we did.
taskkill /IM pythonw.exe /F >nul 2>nul
echo   ... done.

echo.
echo Done. Any admin window can be closed by pressing 0 then Enter.
echo.
pause
