@echo off
REM ===========================================================================
REM  2_ATM.bat  -  THE CASH MACHINE (what a customer uses)
REM
REM  Opens the ATM screen: card reader, PIN keypad, menu.
REM  It shows ONLY the card currently in the machine - never anyone else's
REM  account, and never the bank's transaction list.
REM
REM  Run 1_BANK.bat first, otherwise the ATM says OUT OF SERVICE.
REM  You can open this more than once to have two cash machines.
REM ===========================================================================

title AAST Bank - ATM
cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" (
    set "PYW=.venv\Scripts\pythonw.exe"
    goto got_python
)
where pythonw >nul 2>nul
if %errorlevel%==0 (
    set "PYW=pythonw"
    goto got_python
)
where pyw >nul 2>nul
if %errorlevel%==0 (
    set "PYW=pyw"
    goto got_python
)
REM  Fall back to normal python if the windowed launcher is missing.
where py >nul 2>nul
if %errorlevel%==0 (
    set "PYW=py"
    goto got_python
)
set "PYW=python"
:got_python

REM  pythonw runs the window WITHOUT a black console box behind it,
REM  which is what makes this look like a real cash machine.
start "" %PYW% atm_gui.py
