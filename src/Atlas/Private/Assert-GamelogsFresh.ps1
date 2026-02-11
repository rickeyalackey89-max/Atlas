# Extracted into module Private/
# Source: run_today_and_export.ps1:52-66
function Assert-GamelogsFresh {
    param(
        [Parameter(Mandatory=$true)][string]$GamelogsPath,
        [int]$MaxStaleDays = 2
    )
    if (-not (Test-Path $GamelogsPath)) { throw "Freshness guard FAILED: missing nba_gamelogs.csv at $GamelogsPath" }
    $mx = & $PY -c "import pandas as pd; df=pd.read_csv(r'$GamelogsPath', usecols=['game_date']); df['game_date']=pd.to_datetime(df['game_date'], errors='coerce'); print(df['game_date'].max().date())"
    if ($LASTEXITCODE -ne 0) { throw "Freshness guard FAILED: could not compute max(game_date) for $GamelogsPath" }
    $mxDate = [datetime]::Parse($mx)
    $staleDays = (New-TimeSpan -Start $mxDate -End (Get-Date)).Days
    if ($staleDays -gt $MaxStaleDays) {
        throw "Freshness guard FAILED: nba_gamelogs.csv is stale. max_game_date=$($mxDate.ToString('yyyy-MM-dd')) staleDays=$staleDays threshold=$MaxStaleDays"
    }
    Write-Host ("[OK] nba_gamelogs.csv fresh: max_game_date={0} (staleDays={1})" -f $mxDate.ToString('yyyy-MM-dd'), $staleDays)
}

