param(
    [string]$KeyPath,
    [string]$Model = "gpt-5.3-spark",
    [string]$Lane = "5.3-spark"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($KeyPath)) {
    $KeyPath = Join-Path $repoRoot "OpenAI.txt"
    if (-not (Test-Path -LiteralPath $KeyPath)) {
        $docsKey = Join-Path $repoRoot "docs\MLB_info_DO_NOT_DELETE\OpenAI.txt"
        if (Test-Path -LiteralPath $docsKey) {
            $KeyPath = $docsKey
        }
    }
    if (-not (Test-Path -LiteralPath $KeyPath)) {
        $infoKey = Join-Path $repoRoot "MLB_info_DO_NOT_DELETE\OpenAI.txt"
        if (Test-Path -LiteralPath $infoKey) {
            $KeyPath = $infoKey
        }
    }
}

if (-not (Test-Path -LiteralPath $KeyPath)) {
    throw "OpenAI key file not found: $KeyPath"
}

$apiKey = (Get-Content -Raw -LiteralPath $KeyPath).Trim()
if ([string]::IsNullOrWhiteSpace($apiKey)) {
    throw "OpenAI key file is empty: $KeyPath"
}

$env:OPENAI_API_KEY = $apiKey
$env:ATLAS_OPENAI_EVALUATOR_ENABLED = "1"
$env:ATLAS_OPENAI_EVALUATOR_MODEL = $Model
$env:ATLAS_OPENAI_EVALUATOR_LANE = $Lane

Write-Host "Atlas MLB OpenAI evaluator environment is configured for this PowerShell session." -ForegroundColor Green
Write-Host "Model: $Model" -ForegroundColor DarkGray
Write-Host "Lane: $Lane" -ForegroundColor DarkGray
Write-Host "Key source: $KeyPath" -ForegroundColor DarkGray
Write-Host "API key value was not printed." -ForegroundColor DarkGray
