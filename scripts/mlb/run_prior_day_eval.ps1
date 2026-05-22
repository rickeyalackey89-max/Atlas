param(
    [string]$Date = "",
    [string]$RunId = "",
    [ValidateSet("auto", "live", "replay", "test")]
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
        [string]$StageRunId = "",
        [string[]]$CommandArgs,
        [string]$OutputPath
    )

    Write-ProgressJson @{ stage = "${Stage}_start"; date = $Date; run_id = $StageRunId }
    $oldErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $output = & $CommandArgs[0] @($CommandArgs[1..($CommandArgs.Count - 1)]) 2>&1
    $ErrorActionPreference = $oldErrorActionPreference
    $exitCode = $LASTEXITCODE
    $output | Set-Content -Encoding utf8 $OutputPath
    if ($exitCode -ne 0) {
        Write-ProgressJson @{ stage = "${Stage}_failed"; date = $Date; run_id = $StageRunId; exit_code = $exitCode; log = $OutputPath }
        throw "${Stage} failed with exit code $exitCode. See $OutputPath"
    }
    Write-ProgressJson @{ stage = "${Stage}_complete"; date = $Date; run_id = $StageRunId; log = $OutputPath }
}

function Resolve-RunIdsForDate {
    param([string]$TargetDate, [string]$Scope)

    $targetDateKey = $TargetDate.Replace("-", "")
    $roots = @()
    if ($Scope -eq "live") {
        $roots = @(Join-Path $repoRoot "data\mlb\live_runs")
    } elseif ($Scope -eq "replay") {
        $roots = @(Join-Path $repoRoot "data\mlb\replay_runs")
    } elseif ($Scope -eq "test") {
        $roots = @(Join-Path $repoRoot "data\mlb\test_runs")
    } else {
        $roots = @(
            (Join-Path $repoRoot "data\mlb\live_runs"),
            (Join-Path $repoRoot "data\mlb\replay_runs"),
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
                $manifestRaw = Get-Content -Raw -LiteralPath $manifestPath
                $manifestDate = ""
                $dateMatches = [regex]::Matches($manifestRaw, '"game_date_filter"\s*:\s*"([^"]+)"')
                if ($dateMatches.Count -gt 0) {
                    $manifestDate = [string]$dateMatches[0].Groups[1].Value
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

    if ($Scope -eq "auto") {
        $bestPriority = ($candidates | Measure-Object -Property Priority -Minimum).Minimum
        $candidates = @($candidates | Where-Object { $_.Priority -eq $bestPriority })
    }
    return @($candidates | Sort-Object Priority, LastWriteTimeUtc, RunId | Select-Object -ExpandProperty RunId -Unique)
}

if (-not $SkipBoxscoreFetch) {
    Invoke-LoggedCommand `
        -Stage "fetch_boxscores" `
        -StageRunId "" `
        -CommandArgs @("uv", "run", "atlas-mlb", "fetch", "statsapi-boxscores-bulk", "--start-date", $Date, "--end-date", $Date, "--json") `
        -OutputPath (Join-Path $LogRoot "fetch_boxscores.json")
}

$runIds = @()
if ([string]::IsNullOrWhiteSpace($RunId)) {
    $runIds = @(Resolve-RunIdsForDate -TargetDate $Date -Scope $RunScope)
} else {
    $runIds = @($RunId)
}

$runResults = @()
foreach ($targetRunId in $runIds) {
    $safeRunId = $targetRunId -replace '[^A-Za-z0-9_.-]', '_'
    Invoke-LoggedCommand `
        -Stage "audit_eval" `
        -StageRunId $targetRunId `
        -CommandArgs @("uv", "run", "atlas-mlb", "audit", "eval", "--run-id", $targetRunId, "--json") `
        -OutputPath (Join-Path $LogRoot "audit_eval_$safeRunId.json")

    $evalDir = Join-Path $repoRoot "data\mlb\eval\$targetRunId"
    $runResults += [pscustomobject]@{
        date = $Date
        run_id = $targetRunId
        eval_dir = $evalDir
        eval_legs_csv = Join-Path $evalDir "eval_legs.csv"
        eval_legs_json = Join-Path $evalDir "eval_legs.json"
        eval_slips_csv = Join-Path $evalDir "eval_slips.csv"
        eval_slips_json = Join-Path $evalDir "eval_slips.json"
        slip_eval_json = Join-Path $evalDir "slip_eval.json"
        log = Join-Path $LogRoot "audit_eval_$safeRunId.json"
    }
}

$result = [pscustomobject]@{
    date = $Date
    run_scope = $RunScope
    run_count = $runResults.Count
    run_ids = @($runResults | Select-Object -ExpandProperty run_id)
    runs = $runResults
    logs = $LogRoot
}
$result | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 (Join-Path $LogRoot "result.json")
$result | ConvertTo-Json -Depth 5
