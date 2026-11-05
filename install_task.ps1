# 注册/卸载 Windows 每日计划任务
#
# 用法（普通 PowerShell 即可，不需要管理员）：
#   powershell -ExecutionPolicy Bypass -File .\install_task.ps1
#   powershell -ExecutionPolicy Bypass -File .\install_task.ps1 -Time 08:30 -Minutes 26
#   powershell -ExecutionPolicy Bypass -File .\install_task.ps1 -RunNow
#   powershell -ExecutionPolicy Bypass -File .\install_task.ps1 -Uninstall
#
# 说明：
#   * LogonType=Interactive：只有你登录 Windows 后才运行，
#     这样触发 -12 人机验证时浏览器能弹出来让你滑一下；
#   * StartWhenAvailable：到点时电脑关机/睡眠，开机后会补跑；
#   * MultipleInstances=IgnoreNew：不会和手动运行撞车（daily.py 还有文件锁）。

param(
    [string]$TaskName = "ZhihuishuDaily25Min",
    [string]$Time = "09:00",
    [int]$Minutes = 26,
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
        Write-Host "已删除计划任务：$TaskName"
    } else {
        Write-Host "计划任务不存在：$TaskName"
    }
    exit 0
}

$python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $cmd) { throw "找不到 python。请先安装 Python 3.10+，或在项目目录创建 .venv。" }
    $python = $cmd.Source
}

$daily = Join-Path $Root "daily.py"
if (-not (Test-Path $daily)) { throw "找不到 daily.py：$daily" }

New-Item -ItemType Directory -Force -Path (Join-Path $Root "logs"), (Join-Path $Root "state") | Out-Null

$argLine = "`"$daily`" --config `"$Root\config.yaml`" --minutes $Minutes"
$action = New-ScheduledTaskAction -Execute $python -Argument $argLine -WorkingDirectory $Root

$trigger = New-ScheduledTaskTrigger -Daily -At $Time -RandomDelay (New-TimeSpan -Minutes 15)
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -WakeToRun `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 10)

$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null

Write-Host "已注册计划任务：$TaskName"
Write-Host "  运行时间：每天 $Time"
Write-Host "  每日分钟：$Minutes"
Write-Host "  Python  ：$python"
Write-Host "  工作目录：$Root"
Write-Host ""
Write-Host "首次使用前请先手动扫码登录："
Write-Host "  `"$python`" `"$daily`" --login"
Write-Host ""
Write-Host "查看任务：schtasks /Query /TN `"$TaskName`" /V /FO LIST"
Write-Host "立即测试：schtasks /Run /TN `"$TaskName`""
Write-Host "删除任务：powershell -ExecutionPolicy Bypass -File .\install_task.ps1 -Uninstall"

if ($RunNow) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "已立即启动一次。"
}
