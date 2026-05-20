param(
    [string]$KeyPath,
    [string]$Model = "gpt-5.4-mini"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($KeyPath)) {
    $KeyPath = Join-Path $repoRoot "OpenAI.txt"
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

Write-Host "Atlas MLB OpenAI evaluator environment is configured for this PowerShell session." -ForegroundColor Green
Write-Host "Model: $Model" -ForegroundColor DarkGray
Write-Host "Key source: $KeyPath" -ForegroundColor DarkGray
Write-Host "API key value was not printed." -ForegroundColor DarkGray
