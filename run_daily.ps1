# run_daily.ps1 - Runs the full daily scan + report pipeline:
#   1. src/full_universe_analysis.py  (scans NASDAQ+NYSE, ethical filter applied,
#      writes runs/full_universe_results.csv + archives a timestamped copy)
#   2. src/track_outcomes.py          (2026-07: updates runs/outcome_tracking.csv
#      with today's new candidates + rechecks previously-pending ones, so the
#      report below can show a real "Track record" stat)
#   3. src/build_report.py            (builds runs/report.html from that CSV)
#   4. Archives a timestamped copy of report.html too, so past reports stay
#      browsable (full_universe_analysis.py already archives its own CSV; this
#      script adds the same treatment for the HTML report, which it doesn't).
#
# Meant to be run unattended (Windows Task Scheduler) or double-clicked by hand.
# Every run's console output is also saved to a timestamped log file, so a
# failed overnight run can be diagnosed after the fact - see run_daily.ps1's
# own log at runs/archive/logs/.
#
# Run manually:
#   powershell -ExecutionPolicy Bypass -File run_daily.ps1
# Register as a daily scheduled task:
#   powershell -ExecutionPolicy Bypass -File register_scheduled_task.ps1

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RepoRoot

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogDir = Join-Path $RepoRoot "runs\archive\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir "run_daily_$Timestamp.log"

function Write-Log {
    param([string]$Message)
    $Line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Message"
    Write-Host $Line
    Add-Content -Path $LogFile -Value $Line
}

Write-Log "=== Daily scan + report run starting ==="

try {
    # Deliberately not redirecting stderr (2>&1) from these native python calls:
    # every WARNING/error in these scripts is emitted via print() to stdout, and
    # PowerShell 5.1 wraps a redirected native-command stderr line in a
    # NativeCommandError (flips $? to false even on a real exit code 0) - so
    # redirecting here would make LASTEXITCODE checks unreliable for no benefit.
    Write-Log "Step 1/3: running full_universe_analysis.py (this scans the full NASDAQ+NYSE universe and can take tens of minutes)..."
    python src\full_universe_analysis.py | Tee-Object -FilePath $LogFile -Append
    if ($LASTEXITCODE -ne 0) {
        throw "full_universe_analysis.py exited with code $LASTEXITCODE"
    }

    Write-Log "Step 2/3: running track_outcomes.py..."
    python src\track_outcomes.py | Tee-Object -FilePath $LogFile -Append
    if ($LASTEXITCODE -ne 0) {
        throw "track_outcomes.py exited with code $LASTEXITCODE"
    }

    Write-Log "Step 3/3: running build_report.py..."
    python src\build_report.py | Tee-Object -FilePath $LogFile -Append
    if ($LASTEXITCODE -ne 0) {
        throw "build_report.py exited with code $LASTEXITCODE"
    }

    # build_report.py always overwrites runs/report.html - archive a timestamped
    # copy here (same "keep every run" philosophy as the CSV archive) so a
    # previous day's report stays viewable even after tomorrow's run replaces it.
    $ReportArchiveDir = Join-Path $RepoRoot "runs\archive\reports"
    New-Item -ItemType Directory -Force -Path $ReportArchiveDir | Out-Null
    $ReportSrc = Join-Path $RepoRoot "runs\report.html"
    if (Test-Path $ReportSrc) {
        $ReportDest = Join-Path $ReportArchiveDir "report_$Timestamp.html"
        Copy-Item -Path $ReportSrc -Destination $ReportDest -Force
        Write-Log "Archived report to $ReportDest"
    }

    Write-Log "=== Run completed successfully. Latest report: runs\report.html ==="
}
catch {
    Write-Log "=== RUN FAILED: $($_.Exception.Message) ==="
    exit 1
}
