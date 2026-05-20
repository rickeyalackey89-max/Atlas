param(
    [string]$CorpusDir = "data\mlb\eval\corpus_replay_20260426_20260518_live_context_fix_v1",
    [string]$OutputDir = "data\mlb\model\cat_probability_kernel_v6_23date_live_context",
    [string]$Version = "mlb_cat_over_residual_v6_23date_live_context",
    [string]$Iterations = "200,400,600",
    [string]$LearningRates = "0.03,0.06",
    [string]$Depths = "4",
    [string]$ResidualScales = "0.25,0.35,0.50,0.65",
    [double]$ResidualClip = 0.20,
    [double]$PLo = 0.03,
    [double]$PHi = 0.97,
    [double]$L2LeafReg = 6.0,
    [int]$MinDataInLeaf = 80,
    [int]$RandomSeed = 42,
    [switch]$NoTailWindow
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $repoRoot

$resolvedOutput = Join-Path $repoRoot $OutputDir
New-Item -ItemType Directory -Force -Path $resolvedOutput | Out-Null
$logPath = Join-Path $resolvedOutput "train.log"
$pidPath = Join-Path $resolvedOutput "train.pid"
$startedAt = Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"

"[CAT-LODO] starting $startedAt" | Set-Content -Path $logPath -Encoding UTF8
"[CAT-LODO] repo=$repoRoot" | Add-Content -Path $logPath -Encoding UTF8
"[CAT-LODO] corpus=$CorpusDir" | Add-Content -Path $logPath -Encoding UTF8
"[CAT-LODO] output=$OutputDir" | Add-Content -Path $logPath -Encoding UTF8
"[CAT-LODO] version=$Version" | Add-Content -Path $logPath -Encoding UTF8

if (-not $NoTailWindow) {
    $tailCommand = "Set-Location '$repoRoot'; Write-Host 'Tailing MLB CAT LODO: $logPath'; Get-Content -LiteralPath '$logPath' -Tail 80 -Wait | ForEach-Object { `$_ -replace [char]0, '' }"
    Start-Process powershell -ArgumentList @("-NoExit", "-Command", $tailCommand)
}

$PID | Set-Content -Path $pidPath -Encoding UTF8

$cmd = @(
    "uv", "run", "python", "scripts\mlb\train_cat_probability_kernel.py",
    "--root", ".",
    "--corpus-dir", $CorpusDir,
    "--output-dir", $OutputDir,
    "--version", $Version,
    "--iterations", $Iterations,
    "--learning-rates", $LearningRates,
    "--depths", $Depths,
    "--residual-scales", $ResidualScales,
    "--residual-clip", [string]$ResidualClip,
    "--p-lo", [string]$PLo,
    "--p-hi", [string]$PHi,
    "--l2-leaf-reg", [string]$L2LeafReg,
    "--min-data-in-leaf", [string]$MinDataInLeaf,
    "--random-seed", [string]$RandomSeed
)

"[CAT-LODO] command=$($cmd -join ' ')" | Add-Content -Path $logPath -Encoding UTF8

$exe = $cmd[0]
$cmdArgs = $cmd[1..($cmd.Count - 1)]
& $exe @cmdArgs 2>&1 | ForEach-Object {
    $line = [string]$_
    Write-Output $line
    Add-Content -Path $logPath -Value $line -Encoding UTF8
}
$exitCode = $LASTEXITCODE

"[CAT-LODO] finished $(Get-Date -Format "yyyy-MM-ddTHH:mm:ssK") exit_code=$exitCode" | Add-Content -Path $logPath -Encoding UTF8
exit $exitCode
