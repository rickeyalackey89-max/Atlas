function Assert-AtlasModelAllowed {
    [CmdletBinding()]
    param(
        [switch]$AllowModelRun
    )

    # Hard kill-switch via environment variable
    if ($env:ATLAS_DISABLE_MODEL -eq "1" -and -not $AllowModelRun) {
        throw "Atlas model run is disabled (ATLAS_DISABLE_MODEL=1). Refusing to run model."
    }

    # Require explicit opt-in even if env var isn't set
    if (-not $AllowModelRun) {
        throw "Refusing to run Atlas model without -AllowModelRun (safety: model can freeze the PC)."
    }
}