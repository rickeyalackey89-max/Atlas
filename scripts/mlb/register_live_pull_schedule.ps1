param(
    [string]$RepoRoot = "",
    [string]$TaskPrefix = "AtlasMLBLive",
    [string[]]$Windows = @("11:00", "14:30", "17:00", "19:00"),
    [string]$StateCode = "MO",
    [switch]$Replace
)

$ErrorActionPreference = "Stop"

if (-not $RepoRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

$runner = Join-Path $RepoRoot "scripts\mlb\run_live_model.ps1"
if (-not (Test-Path $runner)) {
    throw "Missing live runner script: $runner"
}

foreach ($window in $Windows) {
    $taskName = "$TaskPrefix-$($window.Replace(':', ''))"
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($existing -and -not $Replace) {
        Write-Host "Exists: $taskName (use -Replace to recreate)"
        continue
    }
    if ($existing -and $Replace) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }

    $trigger = New-ScheduledTaskTrigger -Daily -At $window
    $argument = "-NoProfile -ExecutionPolicy Bypass -File `"$runner`" -RepoRoot `"$RepoRoot`" -StateCode `"$StateCode`""
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argument -WorkingDirectory $RepoRoot
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Hours 2)

    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description "Atlas MLB live model pull at $window local time" | Out-Null
    Write-Host "Registered: $taskName at $window"
}
