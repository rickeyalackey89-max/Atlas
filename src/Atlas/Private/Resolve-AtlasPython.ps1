function Resolve-AtlasPython {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)]
    [string]$AtlasRoot
  )

  Set-StrictMode -Version Latest
  $ErrorActionPreference = 'Stop'

  # Prefer the same candidates you currently use in Resolve-Python
  $candidates = @(
    "C:\Users\rick\AppData\Local\Programs\Python\Python311\python.exe",
    "C:\Users\rick\AppData\Local\Programs\Python\Python310\python.exe",
    "C:\Python311\python.exe"
  )

  foreach ($c in $candidates) {
    if (Test-Path -LiteralPath $c) { return (Resolve-Path -LiteralPath $c).Path }
  }

  $cmd = Get-Command python -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }

  throw "Python not found. Install Python or add it to PATH. (AtlasRoot=$AtlasRoot)"
}