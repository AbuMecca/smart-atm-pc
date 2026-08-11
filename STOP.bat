@echo off
REM ===========================================================================
REM  STOP.bat  -  closes everything the demo opened.
REM
REM  You can also just close the windows by hand; this is only quicker.
REM ===========================================================================

title AAST Bank - Shutdown

echo ============================================================
echo   AAST BANK  -  shutting everything down
echo ============================================================
echo.

echo Closing the website...
taskkill /FI "WINDOWTITLE eq AAST Bank - Website*" /T /F >nul 2>nul
if %errorlevel%==0 (echo   ... closed.) else (echo   ... was not running.)

echo Closing the STM32 link...
taskkill /FI "WINDOWTITLE eq AAST Bank - STM32 Link*" /T /F >nul 2>nul
if %errorlevel%==0 (echo   ... closed.) else (echo   ... was not running.)

echo.
echo Done. The browser tab can just be closed.
echo Any admin window closes with 0 then Enter.
echo.
pause
