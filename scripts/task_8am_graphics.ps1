# Daily Graphics Generation Task - 8:00 AM
# ====================================
# Automated daily subscriber content generation

param(
    [switch]$TestRun = $false
)

$ErrorActionPreference = "Stop"

# Configuration
$AtlasRoot = "C:\Users\13142\Atlas\NBA"
$LogFile = "$AtlasRoot\data\output\logs\daily_graphics_$(Get-Date -Format 'yyyyMMdd').log"

function Write-Log {
    param([string]$Message)
    $Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $LogEntry = "[$Timestamp] $Message"
    Write-Host $LogEntry
    Add-Content -Path $LogFile -Value $LogEntry
}

try {
    # Ensure log directory exists
    $LogDir = Split-Path $LogFile -Parent
    if (!(Test-Path $LogDir)) {
        New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    }
    
    Write-Log "=== DAILY GRAPHICS GENERATION START ==="
    Write-Log "Atlas Root: $AtlasRoot"
    Write-Log "Test Run: $TestRun"
    
    # Change to Atlas directory
    Set-Location $AtlasRoot
    Write-Log "Working directory: $(Get-Location)"
    
    if ($TestRun) {
        Write-Log "TEST MODE: Running graphics generation on latest existing run"
        
        # Find latest run
        $RunsDir = "$AtlasRoot\data\output\runs"
        $LatestRun = Get-ChildItem $RunsDir | Sort-Object Name -Descending | Select-Object -First 1
        
        if (!$LatestRun) {
            throw "No existing runs found for test"
        }
        
        Write-Log "Using existing run: $($LatestRun.Name)"
        
        # Generate graphics from existing run
        $TodayStr = Get-Date -Format "yyyyMMdd"
        $CsvPath = "$AtlasRoot\data\output\graphics\daily_top_picks_$TodayStr.csv"
        
        python -m tools.generate_daily_graphics_csv --run-id $LatestRun.Name --output $CsvPath
        if ($LASTEXITCODE -ne 0) { throw "CSV generation failed" }
        
        python -m tools.generate_daily_graphics --csv $CsvPath --output-dir "$AtlasRoot\data\output\graphics"
        if ($LASTEXITCODE -ne 0) { throw "Visual graphics generation failed" }
        
        Write-Log "✅ Test graphics generation completed successfully"
        
    } else {
        Write-Log "LIVE MODE: Running full Atlas live pipeline with integrated graphics"
        
        # Run full Atlas live pipeline (includes integrated graphics generation)
        python -m Atlas.cli live --scheduled
        if ($LASTEXITCODE -ne 0) { 
            throw "Atlas live run failed with exit code: $LASTEXITCODE"
        }
        
        Write-Log "✅ Live Atlas run with graphics completed successfully"
    }
    
    # Verify outputs
    $GraphicsDir = "$AtlasRoot\data\output\graphics"
    $TodayStr = Get-Date -Format "yyyyMMdd"
    
    $ExpectedFiles = @(
        "$GraphicsDir\daily_top_picks_$TodayStr.csv",
        "$GraphicsDir\daily_goblin_picks.png",
        "$GraphicsDir\daily_standard_picks.png", 
        "$GraphicsDir\daily_demon_picks.png",
        "$GraphicsDir\daily_summary.png"
    )
    
    $MissingFiles = @()
    foreach ($File in $ExpectedFiles) {
        if (!(Test-Path $File)) {
            $MissingFiles += $File
        }
    }
    
    if ($MissingFiles.Count -gt 0) {
        Write-Log "⚠️ Some expected files missing:"
        foreach ($Missing in $MissingFiles) {
            Write-Log "   Missing: $Missing"
        }
    } else {
        Write-Log "✅ All expected graphics files generated successfully"
    }
    
    # List generated files
    Write-Log "Generated files:"
    foreach ($File in $ExpectedFiles) {
        if (Test-Path $File) {
            $Size = (Get-Item $File).Length
            Write-Log "   ✅ $File ($Size bytes)"
        }
    }
    
    Write-Log "=== DAILY GRAPHICS GENERATION COMPLETE ==="
    
} catch {
    Write-Log "❌ ERROR: $($_.Exception.Message)"
    Write-Log "Stack trace: $($_.ScriptStackTrace)"
    
    # Send notification (you could add email/SMS here)
    Write-Log "Graphics generation failed - manual intervention required"
    
    exit 1
}
