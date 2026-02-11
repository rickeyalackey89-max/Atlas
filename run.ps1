# Stable one-shot runner for Atlas (run once, then exit)
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe   = "C:\Users\rick\AppData\Local\Programs\Python\Python311\python.exe"

if (-not (Test-Path $PythonExe)) {
  Write-Error "Python not found: $PythonExe"
  exit 1
}

$env:PYTHONPATH = Join-Path $ProjectRoot "src"

& $PythonExe (Join-Path $ProjectRoot "run_today.py")
exit $LASTEXITCODE