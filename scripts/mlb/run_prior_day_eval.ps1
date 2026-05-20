param(
    [string]$Date = "",
    [string]$RunId = "",
    [ValidateSet("auto", "live", "test")]
    [string]$RunScope = "auto",
    [switch]$SkipBoxscoreFetch,
    [string]$LogRoot = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $repoRoot

if ([string]::IsNullOrWhiteSpace($Date)) {
    $Date = (Get-Date).Date.AddDays(-1).ToString("yyyy-MM-dd")
}
$dateKey = $Date.Replace("-", "")

if ([string]::IsNullOrWhiteSpace($LogRoot)) {
    $LogRoot = Join-Path $repoRoot "data\mlb\eval\morning_prior_day_$dateKey"
}
New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null

function Write-ProgressJson {
    param([hashtable]$Item)
    $Item["ts"] = (Get-Date).ToString("o")
    $Item | ConvertTo-Json -Compress | Add-Content -Encoding utf8 (Join-Path $LogRoot "progress.jsonl")
}

function Invoke-LoggedCommand {
    param(
        [string]$Stage,
        [string[]]$CommandArgs,
        [string]$OutputPath
    )

    Write-ProgressJson @{ stage = "${Stage}_start"; date = $Date; run_id = $RunId }
    $output = & $CommandArgs[0] @($CommandArgs[1..($CommandArgs.Count - 1)]) 2>&1
    $exitCode = $LASTEXITCODE
    $output | Set-Content -Encoding utf8 $OutputPath
    if ($exitCode -ne 0) {
        Write-ProgressJson @{ stage = "${Stage}_failed"; date = $Date; run_id = $RunId; exit_code = $exitCode; log = $OutputPath }
        throw "${Stage} failed with exit code $exitCode. See $OutputPath"
    }
    Write-ProgressJson @{ stage = "${Stage}_complete"; date = $Date; run_id = $RunId; log = $OutputPath }
}

function Resolve-RunIdForDate {
    param([string]$TargetDate, [string]$Scope)

    $targetDateKey = $TargetDate.Replace("-", "")
    $roots = @()
    if ($Scope -eq "live") {
        $roots = @(Join-Path $repoRoot "data\mlb\live_runs")
    } elseif ($Scope -eq "test") {
        $roots = @(Join-Path $repoRoot "data\mlb\test_runs")
    } else {
        $roots = @(
            (Join-Path $repoRoot "data\mlb\live_runs"),
            (Join-Path $repoRoot "data\mlb\test_runs"),
            (Join-Path $repoRoot "data\mlb\runs")
        )
    }

    $candidates = @()
    for ($i = 0; $i -lt $roots.Count; $i++) {
        $root = $roots[$i]
        if (-not (Test-Path -LiteralPath $root)) {
            continue
        }
        Get-ChildItem -LiteralPath $root -Directory | ForEach-Object {
            $manifestPath = Join-Path $_.FullName "run_manifest.json"
            $scoredPath = Join-Path $_.FullName "scored_legs.json"
            $dateMatched = $false
            if (Test-Path -LiteralPath $manifestPath) {
                $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json -AsHashtable
                $manifestDate = [string]$manifest["game_date_filter"]
                if ([string]::IsNullOrWhiteSpace($manifestDate) -and $manifest.ContainsKey("engine_board")) {
                    $engineBoard = $manifest["engine_board"]
                    if ($engineBoard -is [hashtable] -and $engineBoard.ContainsKey("game_date_filter")) {
                        $manifestDate = [string]$engineBoard["game_date_filter"]
                    }
                }
                $dateMatched = $manifestDate -eq $TargetDate
            } elseif ($_.Name -like "*$targetDateKey*") {
                $dateMatched = Test-Path -LiteralPath $scoredPath
            }

            if ($dateMatched -and (Test-Path -LiteralPath $scoredPath)) {
                $candidates += [pscustomobject]@{
                    RunId = $_.Name
                    Priority = $i
                    LastWriteTimeUtc = $_.LastWriteTimeUtc
                    Path = $_.FullName
                }
            }
        }
    }

    if ($candidates.Count -eq 0) {
        throw "No scored MLB run found for $TargetDate in scope '$Scope'. Pass -RunId explicitly if needed."
    }
    return ($candidates | Sort-Object Priority, @{ Expression = "LastWriteTimeUtc"; Descending = $true } | Select-Object -First 1).RunId
}

if (-not $SkipBoxscoreFetch) {
    Invoke-LoggedCommand `
        -Stage "fetch_boxscores" `
        -CommandArgs @("uv", "run", "atlas-mlb", "fetch", "statsapi-boxscores-bulk", "--start-date", $Date, "--end-date", $Date, "--json") `
        -OutputPath (Join-Path $LogRoot "fetch_boxscores.json")
}

if ([string]::IsNullOrWhiteSpace($RunId)) {
    $RunId = Resolve-RunIdForDate -TargetDate $Date -Scope $RunScope
}

Invoke-LoggedCommand `
    -Stage "audit_eval" `
    -CommandArgs @("uv", "run", "atlas-mlb", "audit", "eval", "--run-id", $RunId, "--json") `
    -OutputPath (Join-Path $LogRoot "audit_eval.json")

$evalDir = Join-Path $repoRoot "data\mlb\eval\$RunId"
$result = [pscustomobject]@{
    date = $Date
    run_id = $RunId
    eval_dir = $evalDir
    eval_legs_csv = Join-Path $evalDir "eval_legs.csv"
    eval_legs_json = Join-Path $evalDir "eval_legs.json"
    eval_slips_csv = Join-Path $evalDir "eval_slips.csv"
    eval_slips_json = Join-Path $evalDir "eval_slips.json"
    slip_eval_json = Join-Path $evalDir "slip_eval.json"
    logs = $LogRoot
}
$result | ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 (Join-Path $LogRoot "result.json")
$result | ConvertTo-Json -Depth 4
