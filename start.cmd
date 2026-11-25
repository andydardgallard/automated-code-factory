@echo off
chcp 65001 >nul
setlocal
rem Code Factory launcher for Windows — created by prepare_factory.
rem   start.cmd          — interactive (in the chat: /skill:code-factory)
rem   start.cmd --auto   — fully autonomous
cd /d "%~dp0"
rem The launch directory — the absolute path of the directory holding this launcher (%CD% after
rem the cd above: no trailing backslash). It is the machine-checkable anchor against which the
rem instruction layer resolves the task's repo_path.
set "KIMI_FACTORY_LAUNCH_DIR=%CD%"
rem Subagent model split (primary/secondary) is enabled here automatically.
set KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1
rem Portable user-scope agent catalog: the CLI's PROJECT-scoped profile registry can lose a
rem factory role ("Unknown agent type"), while its USER-scope catalog — %KIMI_CODE_HOME%\agents,
rem else %USERPROFILE%\.kimi-code\agents — survives that loss. Every factory role is copied
rem there BEFORE the CLI starts, with native commands only (a machine without an interpreter still
rem launches), and only this factory's own role profiles are written: the user's agents in that
rem directory are untouched. A refresh that cannot complete ABORTS the launch — a session with
rem missing or stale roles is exactly the failure this fallback exists to prevent.
set "CF_AGENT_ROLES=advisor analyzer business-tester code-reviewer coder diagnostician documenter farukon-expert gui-expert planner refactorer security-auditor skill-manager supervisor tester"
set "CF_AGENT_SRC=%KIMI_FACTORY_LAUNCH_DIR%\.agents\agents\sub-agents"
set "CF_AGENT_DST="
if not defined KIMI_CODE_HOME goto :cf_agent_user_home
set "CF_AGENT_DST=%KIMI_CODE_HOME%\agents"
goto :cf_agent_destination
:cf_agent_user_home
if defined USERPROFILE set "CF_AGENT_DST=%USERPROFILE%\.kimi-code\agents"
:cf_agent_destination
set "CF_AGENT_ERROR="
if not defined CF_AGENT_DST set "CF_AGENT_ERROR=neither KIMI_CODE_HOME nor USERPROFILE is set, so the user-scope agent catalog cannot be located"
if defined CF_AGENT_ERROR goto :cf_agent_result
if not exist "%CF_AGENT_DST%\" mkdir "%CF_AGENT_DST%" 2>nul
if not exist "%CF_AGENT_DST%\" set "CF_AGENT_ERROR=the directory cannot be created: %CF_AGENT_DST%"
if defined CF_AGENT_ERROR goto :cf_agent_result
if not exist "%CF_AGENT_SRC%\" goto :cf_agent_absent
for %%R in (%CF_AGENT_ROLES%) do call :cf_agent_sync_one "%%R"
goto :cf_agent_result
:cf_agent_absent
echo Code Factory: the project agent catalog is absent - %CF_AGENT_SRC% - verifying the user-scope agent catalog instead.
for %%R in (%CF_AGENT_ROLES%) do call :cf_agent_require_one "%%R"
:cf_agent_result
if not defined CF_AGENT_ERROR goto :cf_agent_launch
echo Code Factory: the launch was refused — the user-scope agent catalog could not be refreshed or verified: %CF_AGENT_ERROR%
echo Code Factory: no Kimi session was started — the factory roles would be missing or stale.
exit /b 1
:cf_agent_launch
where kimi >nul 2>&1
if errorlevel 1 (
    echo The kimi command was not found. Install Kimi Code CLI and run again.
    pause
    exit /b 1
)
kimi %*
set "EXITCODE=%ERRORLEVEL%"
if not "%EXITCODE%"=="0" (
    echo The factory exited with code %EXITCODE%.
    pause
)
exit /b %EXITCODE%

:cf_agent_sync_one
if defined CF_AGENT_ERROR goto :eof
if not exist "%CF_AGENT_SRC%\%~1.md" set "CF_AGENT_ERROR=the project agent catalog %CF_AGENT_SRC% is incomplete: %~1.md is missing, so that role would launch from a stale copy - the launch is refused"
if defined CF_AGENT_ERROR goto :eof
copy /y /b "%CF_AGENT_SRC%\%~1.md" "%CF_AGENT_DST%\%~1.md" >nul 2>&1
if errorlevel 1 set "CF_AGENT_ERROR=the profile %~1.md could not be copied to %CF_AGENT_DST% - the launch is refused"
if defined CF_AGENT_ERROR goto :eof
fc /b "%CF_AGENT_SRC%\%~1.md" "%CF_AGENT_DST%\%~1.md" >nul 2>&1
if errorlevel 1 set "CF_AGENT_ERROR=the profile %~1.md could not be refreshed in %CF_AGENT_DST%: the copy there differs from %CF_AGENT_SRC%\%~1.md - the launch is refused"
goto :eof

:cf_agent_require_one
if defined CF_AGENT_ERROR goto :eof
if not exist "%CF_AGENT_DST%\%~1.md" set "CF_AGENT_ERROR=the project agent catalog is absent and the user-scope catalog %CF_AGENT_DST% does not carry %~1.md, so that role would be missing - the launch is refused"
goto :eof
