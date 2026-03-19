param(
  [string]$RepoRoot = ".",

  # Optional: force archive folder name to match replay raw stamp (YYYYMMDD_HHMMSS)
  [string]$StampOverride = $null
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Ensure-Dir([string]$p) {
  if (-not (Test-Path -LiteralPath $p -PathType Container)) {
    New-Item -ItemType Directory -Force -Path $p | Out-Null
  }
}

$root = (Resolve-Path -LiteralPath $RepoRoot).Path

$dashDir = Join-Path $root "data\output\dashboard"
$invalid = Join-Path $dashDir "injury_invalidations_latest.json"
$status  = Join-Path $dashDir "status_latest.json"

if (-not (Test-Path -LiteralPath $invalid -PathType Leaf)) { throw "Missing: $invalid" }
if (-not (Test-Path -LiteralPath $status  -PathType Leaf)) { throw "Missing: $status" }

# Determine stamp
$stamp = if ($StampOverride) { $StampOverride } else { Get-Date -Format "yyyyMMdd_HHmmss" }

# Validate stamp format if provided
if ($stamp -notmatch '^\d{8}_\d{6}$') {
  throw "StampOverride must be YYYYMMDD_HHMMSS (got: $stamp)"
}

$year = $stamp.Substring(0,4)

$archiveRoot = Join-Path $root "data\archives\iael_seed\$year"
$destDir = Join-Path $archiveRoot $stamp

Ensure-Dir $destDir

Copy-Item -LiteralPath $invalid -Destination (Join-Path $destDir "injury_invalidations_latest.json") -Force
Copy-Item -LiteralPath $status  -Destination (Join-Path $destDir "status_latest.json") -Force

$meta = [ordered]@{
  schema      = "atlas.iael_seed.v1"
  created_utc = (Get-Date).ToUniversalTime().ToString("o")
  stamp       = $stamp
  source      = "dashboard_latest_copy"
  invalid_sha = (Get-FileHash $invalid -Algorithm SHA256).Hash
  status_sha  = (Get-FileHash $status  -Algorithm SHA256).Hash
}

($meta | ConvertTo-Json -Depth 6) | Set-Content -LiteralPath (Join-Path $destDir "seed_meta.json") -Encoding UTF8

Write-Host "✅ IAEL seed archived to:"
Write-Host "   $destDir"
