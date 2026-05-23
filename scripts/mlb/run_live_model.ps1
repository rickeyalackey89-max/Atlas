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
$AtlasRoot = Split-Path -Parent $RepoRoot
$AtlasPython = Join-Path $AtlasRoot ".venv\Scripts\python.exe"
$Python = if (Test-Path -LiteralPath $AtlasPython) {
    $AtlasPython
} else {
    Join-Path $RepoRoot ".venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python executable not found. Expected shared Atlas env at $AtlasPython"
}
$AtlasPythonPath = @(
    (Join-Path $AtlasRoot "NBA\src"),
    (Join-Path $AtlasRoot "MLB\src")
) | Where-Object { Test-Path -LiteralPath $_ }

$logRoot = Join-Path $RepoRoot "data\mlb\live_logs"
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logPath = Join-Path $logRoot "live_$stamp.log"

$argsList = @("-m", "mlb.cli", "live", "--state-code", $StateCode, "--fetch-attempts", "$FetchAttempts")
if ($Date) {
    $argsList += @("--date", $Date)
}
if ($CalibrationArtifact) {
    $argsList += @("--calibration-artifact", $CalibrationArtifact)
}

Push-Location $RepoRoot
$oldPythonPath = $env:PYTHONPATH
try {
    if ($oldPythonPath) {
        $env:PYTHONPATH = "$($AtlasPythonPath -join ';');$oldPythonPath"
    } else {
        $env:PYTHONPATH = ($AtlasPythonPath -join ";")
    }
    "Atlas MLB live run started at $(Get-Date -Format o)" | Tee-Object -FilePath $logPath
    "RepoRoot=$RepoRoot" | Tee-Object -FilePath $logPath -Append
    "Python=$Python" | Tee-Object -FilePath $logPath -Append
    "Command=$Python $($argsList -join ' ')" | Tee-Object -FilePath $logPath -Append
    & $Python @argsList 2>&1 | Tee-Object -FilePath $logPath -Append
    $exitCode = $LASTEXITCODE
    "Atlas MLB live run finished at $(Get-Date -Format o) exit_code=$exitCode" | Tee-Object -FilePath $logPath -Append
    exit $exitCode
}
finally {
    $env:PYTHONPATH = $oldPythonPath
    Pop-Location
}
