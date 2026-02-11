function Invoke-AtlasRunTodayAndExport {
  [CmdletBinding(PositionalBinding = $false)]
  param(
    [Parameter(Mandatory)]
    [string]$AtlasRoot,

    # Guardrails
    [int]$TimeoutSeconds = 3600,  # 60 min
    [int]$CpuCoreMask = 1,        # 1 = core0 only; 3 = cores 0-1; 15 = cores 0-3
    [ValidateSet('Idle','BelowNormal','Normal')]
    [string]$Priority = 'BelowNormal',

    # Back-compat: accept -Shell if callers still pass it (ignored now)
    [ValidateSet('pwsh','powershell')]
    [string]$Shell = 'pwsh',

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
  )

  Set-StrictMode -Version Latest
  $ErrorActionPreference = 'Stop'

  $py = Resolve-AtlasPython -AtlasRoot $AtlasRoot

  # Apply BLAS/OpenMP caps BEFORE python starts (inheritance matters)
  $env:OMP_NUM_THREADS        = "1"
  $env:MKL_NUM_THREADS        = "1"
  $env:OPENBLAS_NUM_THREADS   = "1"
  $env:NUMEXPR_NUM_THREADS    = "1"
  $env:BLIS_NUM_THREADS       = "1"
  $env:VECLIB_MAXIMUM_THREADS = "1"
  $env:PYTHONUNBUFFERED       = "1"

  # Discover model entrypoint (so we don't hardcode the wrong path)
  $candidates = @(
    (Join-Path $AtlasRoot 'tools\run_today.py'),
    (Join-Path $AtlasRoot 'tools\run_today_and_export.py'),
    (Join-Path $AtlasRoot 'tools\run_model.py'),
    (Join-Path $AtlasRoot 'scripts\run_today.py'),
    (Join-Path $AtlasRoot 'scripts\run_today_and_export.py'),
    (Join-Path $AtlasRoot 'run_today.py'),
    (Join-Path $AtlasRoot 'run_today_and_export.py'),
    (Join-Path $AtlasRoot 'src\run_today.py'),
    (Join-Path $AtlasRoot 'src\run_today_and_export.py')
  )

  $entry = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
  if (-not $entry) {
    throw "Missing model entrypoint. Searched: $($candidates -join '; ')"
  }

  $pyArgs = @($entry) + $Args

  Write-Host "=== Atlas: Thread caps applied (OMP/MKL/OPENBLAS/NUMEXPR/BLIS=1) ==="
  Write-Host "=== Atlas: Run model (python direct) ==="
  Write-Host "=== Atlas: Python exe === $py"
  Write-Host "=== Atlas: Python entry === $entry"

 if ($null -ne $Args -and @($Args).Count -gt 0) {
  Write-Host "=== Atlas: Python args === $(@($Args) -join ' ')"
}

  Write-Host "=== Atlas: CPU mask === $CpuCoreMask  Priority === $Priority  TimeoutSeconds === $TimeoutSeconds"

  $p = Start-Process -FilePath $py -ArgumentList $pyArgs -WorkingDirectory $AtlasRoot -NoNewWindow -PassThru
  Write-Host "=== Atlas: Model PID === $($p.Id)"

  try {
    try { $p.PriorityClass = [System.Diagnostics.ProcessPriorityClass]::$Priority } catch {}
    try { $p.ProcessorAffinity = [IntPtr]::new($CpuCoreMask) } catch {}

    if ($TimeoutSeconds -gt 0) {
      if (-not $p.WaitForExit($TimeoutSeconds * 1000)) {
        Write-Error "=== Atlas: TIMEOUT ($TimeoutSeconds s). Killing model process tree... ==="
        try { $p.Kill($true) } catch { try { $p.Kill() } catch {} }
        throw "Model timed out after $TimeoutSeconds seconds"
      }
    } else {
      $p.WaitForExit()
    }

    if ($p.ExitCode -ne 0) {
      throw "Model failed with exit code $($p.ExitCode)"
    }
  }
  finally {
    try { $p.Dispose() } catch {}
  }
}