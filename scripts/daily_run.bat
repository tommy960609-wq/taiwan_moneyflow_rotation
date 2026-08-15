@echo off
REM Taiwan Moneyflow Rotation - one-click unattended daily run (Milestone 6).
REM Thin wrapper so Windows Task Scheduler (or a manual double-click) can launch the
REM PowerShell orchestrator wrapper without needing to know PowerShell's invocation
REM syntax. With no arguments it performs automatic late-data backfill + today's
REM ready run; date arguments preserve the explicit single-day path. See
REM docs/operations_manual.md for the scheduled task setup steps.
REM
REM Usage:
REM   scripts\daily_run.bat
REM   scripts\daily_run.bat 2026-07-18 2026-07-17

setlocal
set PROJECT_ROOT=C:\Workspace_CN\taiwan_moneyflow_rotation
set DATE_ARG=%1
set PREV_DATE_ARG=%2

if "%DATE_ARG%"=="" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_ROOT%\scripts\daily_run.ps1"
) else if "%PREV_DATE_ARG%"=="" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_ROOT%\scripts\daily_run.ps1" -Date %DATE_ARG%
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_ROOT%\scripts\daily_run.ps1" -Date %DATE_ARG% -PrevDate %PREV_DATE_ARG%
)

exit /b %ERRORLEVEL%
