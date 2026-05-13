param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]] $ListenerArgs
)

$ErrorActionPreference = "Stop"
$AtlasRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = Join-Path $AtlasRoot ".venv314\Scripts\python.exe"

if (-not (Test-Path $Python)) {
  $Python = "python"
}

Push-Location $AtlasRoot
try {
  & $Python -m Atlas.runtime.cli_listener @ListenerArgs
  exit $LASTEXITCODE
}
finally {
  Pop-Location
}
