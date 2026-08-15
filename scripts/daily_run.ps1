# Taiwan Moneyflow Rotation - one-click unattended daily run (Milestone 6).
#
# Runs the automatic late-data backfill + today's ready day via
# scripts/daily_orchestrator.py, using this project's .venv interpreter. An explicit
# -Date keeps the legacy single-day behavior. Designed to be invoked either manually
# or from Windows Task Scheduler (see
# docs/operations_manual.md for the scheduler setup steps -- this script does not create
# a scheduled task itself).
#
# Exit code is passed straight through from the orchestrator:
#   0 = success, no gaps, or all gaps safely deferred/holiday
#   1 = fetch failed
#   2 = pipeline blocked (incl. DQ black-out)
#   3 = unexpected exception
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\daily_run.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\daily_run.ps1 -Date 2026-07-18 -PrevDate 2026-07-17
#   powershell -ExecutionPolicy Bypass -File scripts\daily_run.ps1 -SkipDerived

param(
    [string]$Date = $null,
    [string]$PrevDate = $null,
    [int]$BackfillLookbackDays = 5,
    [switch]$NoBackfill,
    [switch]$SkipDerived
)

$ErrorActionPreference = "Stop"

$ProjectRoot = "C:\Workspace_CN\taiwan_moneyflow_rotation"
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Orchestrator = Join-Path $ProjectRoot "scripts\daily_orchestrator.py"

if (-not (Test-Path $Python)) {
    Write-Error "Python venv not found at $Python. Run the setup steps in README.md first."
    exit 1
}

Set-Location $ProjectRoot

$ArgList = @($Orchestrator)
if ($Date) { $ArgList += @("--date", $Date) }
if ($PrevDate) { $ArgList += @("--prev-date", $PrevDate) }
if ($BackfillLookbackDays -ne 5) { $ArgList += @("--backfill-lookback-days", $BackfillLookbackDays) }
if ($NoBackfill) { $ArgList += @("--no-backfill") }

Write-Host "[daily_run] Starting: $Python $($ArgList -join ' ')"
& $Python @ArgList
$ExitCode = $LASTEXITCODE

Write-Host "[daily_run] Orchestrator exit code: $ExitCode"
switch ($ExitCode) {
    0 { Write-Host "[daily_run] SUCCESS - report generated." }
    1 { Write-Host "[daily_run] FETCH FAILED - network/API issue, no previous data touched. See outputs/logs/." }
    2 { Write-Host "[daily_run] PIPELINE BLOCKED - data quality gate or missing market data. See outputs/logs/. This includes the intentional 'DQ black-out' fail-closed case (spec Ch.9): no formal report is produced on a black-out day." }
    3 { Write-Host "[daily_run] UNEXPECTED EXCEPTION - see outputs/logs/ for the full traceback." }
    default { Write-Host "[daily_run] UNKNOWN exit code $ExitCode." }
}

if ($ExitCode -eq 0 -and -not $SkipDerived) {
    $LedgerScript = Join-Path $ProjectRoot "scripts\run_forward_test_ledger.py"
    $LedgerStarted = Get-Date
    Write-Host "[daily_run] C1 forward-test ledger started at $($LedgerStarted.ToString('o'))"
    try {
        & $Python $LedgerScript --project-root $ProjectRoot
        $DerivedExitCode = $LASTEXITCODE
        if ($DerivedExitCode -ne 0) {
            Write-Host "[daily_run] C1 forward-test ledger failed with exit code $DerivedExitCode (non-fatal)."
        }
        else {
            Write-Host "[daily_run] C1 forward-test ledger finished successfully."
        }
    }
    catch {
        Write-Host "[daily_run] C1 forward-test ledger failed (non-fatal): $($_.Exception.Message)"
    }
    $LedgerElapsed = ((Get-Date) - $LedgerStarted).TotalSeconds
    Write-Host ("[daily_run] C1 forward-test ledger ended; elapsed={0:N2}s" -f $LedgerElapsed)

    if ((Get-Date).DayOfWeek -eq [DayOfWeek]::Saturday) {
        $DiagnosticScript = Join-Path $ProjectRoot "scripts\run_stock_score_diagnostic.py"
        $DiagnosticStarted = Get-Date
        Write-Host "[daily_run] C2 stock-score diagnostic started at $($DiagnosticStarted.ToString('o'))"
        try {
            & $Python $DiagnosticScript
            $DerivedExitCode = $LASTEXITCODE
            if ($DerivedExitCode -ne 0) {
                Write-Host "[daily_run] C2 stock-score diagnostic failed with exit code $DerivedExitCode (non-fatal)."
            }
            else {
                Write-Host "[daily_run] C2 stock-score diagnostic finished successfully."
            }
        }
        catch {
            Write-Host "[daily_run] C2 stock-score diagnostic failed (non-fatal): $($_.Exception.Message)"
        }
        $DiagnosticElapsed = ((Get-Date) - $DiagnosticStarted).TotalSeconds
        Write-Host ("[daily_run] C2 stock-score diagnostic ended; elapsed={0:N2}s" -f $DiagnosticElapsed)
    }
    else {
        Write-Host "[daily_run] C2 stock-score diagnostic skipped (not Saturday)."
    }
}
elseif ($SkipDerived) {
    Write-Host "[daily_run] Derived steps skipped by -SkipDerived."
}
else {
    Write-Host "[daily_run] Derived steps skipped because orchestrator exit code was $ExitCode."
}

exit $ExitCode
