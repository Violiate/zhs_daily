# Register or unregister the Windows Scheduled Task for zhs_daily.
# Kept 100% pure ASCII so Windows PowerShell 5.1 (GBK default) never
# misinterprets UTF-8 byte sequences as smart quotes.
#
# Usage (normal PowerShell, no Admin required):
#   powershell -ExecutionPolicy Bypass -File .\install_task.ps1
#   powershell -ExecutionPolicy Bypass -File .\install_task.ps1 -Time 20:30 -Minutes 26
#   powershell -ExecutionPolicy Bypass -File .\install_task.ps1 -RunNow
#   powershell -ExecutionPolicy Bypass -File .\install_task.ps1 -Uninstall

param(
    [string]$TaskName = "ZhihuishuDaily25Min",
    [Alias("At")]
    [string]$Time = "09:00",
    [int]$Minutes = 26,
    [int]$RandomDelayMinutes = 15,
    [switch]$RunNow,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if ($Uninstall) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "[OK] Unregistered scheduled task: $TaskName"
    } else {
        Write-Host "[INFO] Scheduled task not found: $TaskName"
    }
    exit 0
}

$python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $cmd) {
        throw "Python not found in PATH. Please install Python 3.10+ or create .venv in project root."
    }
    $python = $cmd.Source
}

$daily = Join-Path $Root "daily.py"
if (-not (Test-Path $daily)) {
    throw "daily.py not found: $daily"
}

New-Item -ItemType Directory -Force -Path (Join-Path $Root "logs"), (Join-Path $Root "state") | Out-Null

$configPath = Join-Path $Root "config.yaml"
$argLine = "`"$daily`" --config `"$configPath`" --minutes $Minutes"
$action = New-ScheduledTaskAction -Execute $python -Argument $argLine -WorkingDirectory $Root

if ($RandomDelayMinutes -gt 0) {
    $trigger = New-ScheduledTaskTrigger -Daily -At $Time -RandomDelay (New-TimeSpan -Minutes $RandomDelayMinutes)
} else {
    $trigger = New-ScheduledTaskTrigger -Daily -At $Time
}

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -WakeToRun `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 10)

$userId = if ($env:USERDOMAIN) { "$env:USERDOMAIN\$env:USERNAME" } else { $env:USERNAME }
$principal = New-ScheduledTaskPrincipal -UserId $userId `
    -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null

Write-Host "============================================================"
Write-Host "[OK] Scheduled task registered: $TaskName"
Write-Host "  Schedule Time : Daily at $Time (+ 0~$RandomDelayMinutes min random delay)"
Write-Host "  Daily Target  : $Minutes minutes"
Write-Host "  Python Exe    : $python"
Write-Host "  Working Dir   : $Root"
Write-Host "============================================================"
Write-Host ""
Write-Host "Note: Make sure you have logged in via QR code at least once:"
Write-Host "  python daily.py --login"
Write-Host ""
Write-Host "Useful commands:"
Write-Host "  Run now   : Start-ScheduledTask -TaskName `"$TaskName`""
Write-Host "  Check info: Get-ScheduledTaskInfo -TaskName `"$TaskName`""
Write-Host "  Uninstall : powershell -ExecutionPolicy Bypass -File .\install_task.ps1 -Uninstall"

if ($RunNow) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "[OK] Task started immediately."
}
