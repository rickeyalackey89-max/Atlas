#requires -Version 5.1
[CmdletBinding(SupportsShouldProcess)]
param(
  [string]$RepoRoot = (Get-Location).Path,

  # Keep compatibility stubs at repo root that forward to the module
  [switch]$KeepRootWrappers = $true
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function New-Dir([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path)) {
    New-Item -ItemType Directory -Path $Path | Out-Null
  }
}

$root = (Resolve-Path -LiteralPath $RepoRoot).Path

# Targets
$opsLegacy = Join-Path $root 'ops\ps\legacy'
$toolsDir  = Join-Path $root 'tools'

New-Dir $opsLegacy
New-Dir $toolsDir

# Files
$atlasAudit = Join-Path $root 'Atlas-Audit.ps1'
$runToday   = Join-Path $root 'run_today_and_export.ps1'
$runAll     = Join-Path $root 'run_all_and_publish.ps1'
$liveFeed   = Join-Path $root 'live_feed_publish.ps1'

# 1) Move Atlas-Audit.ps1 into tools\
if (Test-Path -LiteralPath $atlasAudit) {
  $dest = Join-Path $toolsDir 'Atlas-Audit.ps1'
  if ($PSCmdlet.ShouldProcess($atlasAudit, "Move to $dest")) {
    Move-Item -LiteralPath $atlasAudit -Destination $dest -Force
  }
}

# Helper to move a root script to ops\ps\legacy and optionally leave a thin wrapper behind
function Move-LegacyScript {
  param(
    [Parameter(Mandatory)] [string]$Path,
    [Parameter(Mandatory)] [string]$WrapperCommand  # e.g. "today-export" / "publish" / "live-publish"
  )

  if (-not (Test-Path -LiteralPath $Path)) { return }

  $name = Split-Path -Leaf $Path
  $dest = Join-Path $opsLegacy $name

  if ($PSCmdlet.ShouldProcess($Path, "Move to $dest")) {
    Move-Item -LiteralPath $Path -Destination $dest -Force
  }

  if ($KeepRootWrappers) {
    $wrapperText = @"
# Thin compatibility wrapper (generated)
param(
  [Parameter(ValueFromRemainingArguments = `$true)]
  [string[]]`$Args
)

Set-StrictMode -Version Latest
`$ErrorActionPreference = 'Stop'

Import-Module (Join-Path `$PSScriptRoot 'src\Atlas') -Force
Invoke-Atlas $WrapperCommand @Args
"@

    $wrapperPath = Join-Path $root $name
    if ($PSCmdlet.ShouldProcess($wrapperPath, "Create thin wrapper -> Invoke-Atlas $WrapperCommand")) {
      Set-Content -LiteralPath $wrapperPath -Encoding UTF8 -Value $wrapperText
    }
  }
}

# 2) Move legacy root runners and optionally leave wrappers
Move-LegacyScript -Path $runToday -WrapperCommand 'today-export'
Move-LegacyScript -Path $runAll   -WrapperCommand 'publish'
Move-LegacyScript -Path $liveFeed -WrapperCommand 'live-publish'

Write-Host "✅ Cleanup applied." -ForegroundColor Green
Write-Host ("Legacy scripts archived at: {0}" -f $opsLegacy) -ForegroundColor Cyan
if ($KeepRootWrappers) {
  Write-Host "Root wrappers kept for backwards compatibility." -ForegroundColor Cyan
} else {
  Write-Host "Root wrappers NOT kept (entrypoints removed)." -ForegroundColor Yellow
}