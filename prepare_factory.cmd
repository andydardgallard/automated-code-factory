@echo off
chcp 65001 >nul
setlocal
rem ===========================================================================
rem prepare_factory.cmd — prepare a project for running Code Factory (Windows).
rem
rem Usage: prepare_factory.cmd <path-to-project>
rem
rem Git Bash is not needed: the file runs by double-clicking in Explorer or from
rem cmd/PowerShell. All the work is done by prepare_factory.ps1 (PowerShell ships
rem with Windows); this file only forwards the arguments and its exit code.
rem ===========================================================================

rem --- 1. PowerShell ----------------------------------------------------------
where powershell.exe >nul 2>&1
if errorlevel 1 (
    echo PowerShell was not found ^(powershell.exe^). Project preparation is done
    echo by the prepare_factory.ps1 script and requires PowerShell — it ships with
    echo Windows 10/11; if needed, enable it in Windows features.
    echo.
    echo Usage: prepare_factory.cmd ^<path-to-project^>
    set "EXITCODE=1"
    goto :finish
)

rem --- 2. Deployment script ---------------------------------------------------
if not exist "%~dp0prepare_factory.ps1" (
    echo The deployment script prepare_factory.ps1 was not found — it must sit
    echo next to this file ^(%~dp0^). Make sure the factory repository was copied
    echo in full.
    echo.
    echo Usage: prepare_factory.cmd ^<path-to-project^>
    set "EXITCODE=1"
    goto :finish
)

rem --- 3. Run the deployment (arguments are forwarded unchanged) ---------------
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0prepare_factory.ps1" %*
set "EXITCODE=%ERRORLEVEL%"

:finish
rem --- Pause only on a double-click -------------------------------------------
rem On a double-click the console window closes right after exit, so we wait for
rem a keypress. Runs from a console, from another script and from an automated
rem test are not blocked. Two double-click conditions:
rem   1) the file name appears in the cmd.exe command line. We search via
rem      findstr, not find: find can be shadowed by a same-named utility from
rem      PATH (e.g. from Git Bash) and print errors;
rem   2) input comes from the window console: timeout.exe refuses to run with
rem      redirected input (file or pipe) and returns code 1 — otherwise the pause
rem      would block the script or an automated test. The timeout.exe path is
rem      explicit so we do not catch a same-named utility from PATH.
echo %cmdcmdline% | findstr /i /c:"%~nx0" >nul
if errorlevel 1 goto :no_pause
"%SystemRoot%\System32\timeout.exe" /t 0 /nobreak >nul 2>&1
if errorlevel 1 goto :no_pause
pause

:no_pause
exit /b %EXITCODE%
