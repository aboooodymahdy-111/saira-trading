# register_scheduled_task.ps1 - Registers run_daily.ps1 as a daily Windows
# Task Scheduler task so the scan + report run automatically without you
# starting it by hand.
#
# Default time is 21:00 (9 PM) local time - after US market close, so the
# scan reflects a completed trading day. Change $RunTime below and re-run
# this script to update it (re-running replaces the existing task rather
# than creating a duplicate).
#
# Run once, as your normal (non-elevated) user, from the repo root:
#   powershell -ExecutionPolicy Bypass -File register_scheduled_task.ps1
#
# To remove the scheduled task later:
#   Unregister-ScheduledTask -TaskName "SairaTrading-DailyScan" -Confirm:$false

$ErrorActionPreference = "Stop"

$TaskName = "SairaTrading-DailyScan"
$RunTime = "21:00"

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ScriptPath = Join-Path $RepoRoot "run_daily.ps1"

if (-not (Test-Path $ScriptPath)) {
    throw "run_daily.ps1 not found at $ScriptPath - run this script from the repo root."
}

$Action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`"" `
    -WorkingDirectory $RepoRoot

$Trigger = New-ScheduledTaskTrigger -Daily -At $RunTime

# LogonType Interactive: task runs only while you're logged in (screen can be
# locked, that's fine) - no Windows password ever needs to be stored by Task
# Scheduler. LogonType Password (storing your password so it can run even
# fully logged out) needs the password passed directly to
# Register-ScheduledTask, which then triggers an interactive credential
# prompt from a script host that can't display one and fails with "The
# parameter is incorrect" (0x80070057) - confirmed 2026-07. Interactive
# avoids that entirely and is the right trade-off for a home desktop that's
# normally left on and logged in.
# Use the full DOMAIN\User name: a bare username can fail SID resolution in
# the task XML ("The parameter is incorrect" pointing at UserId).
$CurrentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$Principal = New-ScheduledTaskPrincipal -UserId $CurrentUser -LogonType Interactive -RunLevel Limited

$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3) `
    -RestartCount 1 -RestartInterval (New-TimeSpan -Minutes 10)

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Host "Task '$TaskName' already exists - replacing it with the current settings."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger `
    -Principal $Principal -Settings $Settings `
    -Description "Daily Gann Committee Scanner: runs full_universe_analysis.py then build_report.py (see run_daily.ps1)." | Out-Null

Write-Host "Registered scheduled task '$TaskName' to run daily at $RunTime."
Write-Host "It runs while you're logged in (screen can be locked) - not if the PC is fully signed out."
Write-Host "Logs go to runs\archive\logs\, past HTML reports to runs\archive\reports\."
Write-Host "Check it any time in Task Scheduler (taskschd.msc), under the root task folder."
