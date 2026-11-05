# Registers a Windows Scheduled Task for DriftWatch-TE local reference evaluation.
# Runs every Monday at 02:00 AM local time.
#
# Usage (Run as Administrator):
#   powershell -ExecutionPolicy Bypass -File scripts\register_windows_task.ps1

$TaskName = "DriftWatch-TE-Local-Reference"
$ScriptPath = Join-Path (Get-Location) "scripts\run_local_reference.ps1"
$WorkingDirectory = Get-Location

$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-ExecutionPolicy Bypass -File `"$ScriptPath`"" -WorkingDirectory "$WorkingDirectory"
$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At 2:00AM
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Weekly longitudinal evaluation of pinned local reference model for DriftWatch-TE" -Force

Write-Host "Task '$TaskName' successfully registered to run every Monday at 02:00 AM." -ForegroundColor Green

