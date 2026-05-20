param(
    [string]$RepoRoot = "",
    [string]$StateCode = "MO",
    [string]$Date = "",
    [string]$CalibrationArtifact = "",
    [int]$FetchAttempts = 3
)

$ErrorActionPreference = "Stop"

if (-not $RepoRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

$logRoot = Join-Path $RepoRoot "data\mlb\live_logs"
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logPath = Join-Path $logRoot "live_$stamp.log"

$argsList = @("run", "python", "-m", "mlb.cli", "live", "--state-code", $StateCode, "--fetch-attempts", "$FetchAttempts")
if ($Date) {
    $argsList += @("--date", $Date)
}
if ($CalibrationArtifact) {
    $argsList += @("--calibration-artifact", $CalibrationArtifact)
}

Push-Location $RepoRoot
try {
    "Atlas MLB live run started at $(Get-Date -Format o)" | Tee-Object -FilePath $logPath
    "RepoRoot=$RepoRoot" | Tee-Object -FilePath $logPath -Append
    "Command=uv $($argsList -join ' ')" | Tee-Object -FilePath $logPath -Append
    & uv @argsList 2>&1 | Tee-Object -FilePath $logPath -Append
    $exitCode = $LASTEXITCODE
    "Atlas MLB live run finished at $(Get-Date -Format o) exit_code=$exitCode" | Tee-Object -FilePath $logPath -Append
    exit $exitCode
}
finally {
    Pop-Location
}
