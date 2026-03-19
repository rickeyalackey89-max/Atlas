<#
.SYNOPSIS
  League-wide role scenario sim runner (All-Star break / no games).
  - Reads injuries from Sim.txt (Desktop / OneDrive-aware)
  - Runs dev_role_scenario_dump.py per team with throttled parallelism (ThreadJob; PS5/PS7 safe)
  - Auto-fixes name mismatches by rematching outs to roster names found in output CSV
  - Writes one league summary CSV
  - Optionally deletes per-team CSVs afterwards

.USAGE
  pwsh .\tools\Invoke-LeagueSim.ps1 -GtdProb 0.5 -Throttle 6 -KeepCSVs:$false
  powershell .\tools\Invoke-LeagueSim.ps1 -GtdProb 0 -Throttle 4 -KeepCSVs

.NOTES
  - Requires Python available on PATH
  - Requires ThreadJob module (PS7 often has it; PS5 may need install)
#>

param(
  [double]$GtdProb = 0.50,         # probability a GTD is treated as OUT
  [int]$Throttle = 6,              # parallel workers
  [switch]$KeepCSVs = $false,      # keep per-team scenario CSVs (otherwise keep latest per team + summary only)
  [string]$Stats = "PTS,AST,REB",  # stats passed to the tool
  [string]$DebugDir = "C:\Users\rick\projects\Atlas\data\output\debug"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ============================
# Helpers: paths / normalization
# ============================

function Get-DesktopPath {
  [Environment]::GetFolderPath('Desktop')
}

function Get-InjuryFilePath {
  $desktop = Get-DesktopPath
  $p = Join-Path $desktop "Sim.txt"
  if (Test-Path -LiteralPath $p) { return $p }

  $alt = Get-ChildItem -LiteralPath $desktop -Filter "Sim*.txt" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

  if ($null -eq $alt) {
    throw "Could not find Sim.txt on Desktop: $desktop"
  }
  return $alt.FullName
}

function Remove-Diacritics([string]$s) {
  if ([string]::IsNullOrWhiteSpace($s)) { return $s }
  $norm = $s.Normalize([Text.NormalizationForm]::FormD)
  $sb = New-Object System.Text.StringBuilder
  foreach ($c in $norm.ToCharArray()) {
    $uc = [Globalization.CharUnicodeInfo]::GetUnicodeCategory($c)
    if ($uc -ne [Globalization.UnicodeCategory]::NonSpacingMark) { [void]$sb.Append($c) }
  }
  $sb.ToString().Normalize([Text.NormalizationForm]::FormC)
}

function Normalize-Name([string]$name) {
  $x = Remove-Diacritics($name)
  $x = ($x -replace '\s+', ' ').Trim().ToLowerInvariant()
  # remove punctuation (robust, avoids quoting hell)
  $x = $x -replace '[\p{P}]', ''
  $x
}

function Get-LastName([string]$name) {
  if ([string]::IsNullOrWhiteSpace($name)) { return "" }
  $parts = ($name -split '\s+') | Where-Object { $_ }
  if ($parts.Count -eq 0) { return "" }
  $parts[-1]
}

function Best-MatchOutName {
  param(
    [Parameter(Mandatory)][string]$OutName,
    [Parameter(Mandatory)][string[]]$RosterNames
  )

  $outN = Normalize-Name $OutName
  $rosterNorm = @{}
  foreach ($r in $RosterNames) { $rosterNorm[$r] = Normalize-Name $r }

  # 1) exact normalized match
  foreach ($kv in $rosterNorm.GetEnumerator()) {
    if ($kv.Value -eq $outN) { return $kv.Key }
  }

  # 2) last-name match (common)
  $outLast = Normalize-Name (Get-LastName $OutName)
  if (-not [string]::IsNullOrWhiteSpace($outLast) -and $outLast.Length -ge 3) {
    $cands = @()
    foreach ($kv in $rosterNorm.GetEnumerator()) {
      $rLast = Normalize-Name (Get-LastName $kv.Key)
      if ($rLast -eq $outLast) { $cands += $kv.Key }
    }
    if ($cands.Count -eq 1) { return $cands[0] }
    if ($cands.Count -gt 1) {
      # tie-break by first initial
      $outFirst = ((Normalize-Name $OutName) -split ' ')[0]
      $outInit = if ($outFirst.Length -gt 0) { $outFirst.Substring(0,1) } else { "" }
      $best = $cands | Sort-Object {
        $rf = ((Normalize-Name $_) -split ' ')[0]
        $ri = if ($rf.Length -gt 0) { $rf.Substring(0,1) } else { "" }
        if ($ri -eq $outInit) { 0 } else { 1 }
      } | Select-Object -First 1
      return $best
    }
  }

  # 3) contains match on last name substring
  foreach ($kv in $rosterNorm.GetEnumerator()) {
    if (-not [string]::IsNullOrWhiteSpace($outLast) -and $kv.Value -like "*$outLast*") { return $kv.Key }
  }

  return $null
}

function Get-LatestScenarioCsv {
  param([string]$TeamCode)

  Get-ChildItem -LiteralPath $DebugDir -Filter "role_scenario_${TeamCode}_*.csv" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
}

function Scenario-LooksInvalid {
  param([object[]]$CsvRows)

  if (-not $CsvRows -or $CsvRows.Count -eq 0) { return $true }

  $sample = $CsvRows | Select-Object -First 1
  $hasRoleCtx = $sample.PSObject.Properties.Name -contains "role_ctx_removed_budget"
  $hasScenario = $sample.PSObject.Properties.Name -contains "scenario_removed_budget"

  if (-not $hasRoleCtx -and -not $hasScenario) { return $true }

  $nums = @()

  foreach ($r in $CsvRows) {
    $v = $null
    if ($hasRoleCtx) { $v = $r.role_ctx_removed_budget }
    if ((-not $v) -and $hasScenario) { $v = $r.scenario_removed_budget }

    if ($null -ne $v -and "$v".Length -gt 0) {
      $d = 0.0
      if ([double]::TryParse([string]$v, [ref]$d)) { $nums += $d }
    }
  }

  if ($nums.Count -eq 0) { return $true }
  if (($nums | Measure-Object -Maximum).Maximum -le 0.000001) { return $true }

  return $false
}

function Ensure-ThreadJob {
  if (-not (Get-Module -ListAvailable -Name ThreadJob)) {
    throw "ThreadJob module not found. Install it with: Install-Module ThreadJob -Scope CurrentUser"
  }
  Import-Module ThreadJob -ErrorAction Stop | Out-Null
}

function Wait-ForJobSlot([int]$limit) {
  while (@(Get-Job -State Running).Count -ge $limit) {
    Start-Sleep -Milliseconds 120
  }
}

# ============================
# Parse injuries
# ============================

$injPath = Get-InjuryFilePath
Write-Host "Using injury file: $injPath" -ForegroundColor Cyan

$lines = Get-Content -LiteralPath $injPath
if (-not $lines -or $lines.Count -eq 0) { throw "Injury file empty: $injPath" }

# Team header -> code map (expand as needed)
$teamMap = @{
  "Atlanta"="ATL"; "Boston"="BOS"; "Brooklyn"="BKN"; "Charlotte"="CHA"; "Chicago"="CHI";
  "Cleveland"="CLE"; "Dallas"="DAL"; "Denver"="DEN"; "Detroit"="DET"; "Golden State"="GSW"; "Golden St."="GSW";
  "Houston"="HOU"; "Indiana"="IND";
  "LA Clippers"="LAC"; "L.A. Clippers"="LAC"; "Los Angeles Clippers"="LAC";
  "LA Lakers"="LAL"; "L.A. Lakers"="LAL"; "Los Angeles Lakers"="LAL";
  "Memphis"="MEM"; "Miami"="MIA"; "Milwaukee"="MIL"; "Minnesota"="MIN";
  "New Orleans"="NOP"; "New York"="NYK"; "Oklahoma City"="OKC"; "Orlando"="ORL";
  "Philadelphia"="PHI"; "Phoenix"="PHX"; "Portland"="POR"; "Sacramento"="SAC";
  "San Antonio"="SAS"; "Toronto"="TOR"; "Utah"="UTA"; "Washington"="WAS"
}

$OutLocks = @{}  # team -> HashSet[string]
$GTD      = @{}  # team -> HashSet[string]

function Ensure-Team([string]$tm) {
  if (-not $OutLocks.ContainsKey($tm)) { $OutLocks[$tm] = New-Object 'System.Collections.Generic.HashSet[string]' }
  if (-not $GTD.ContainsKey($tm))      { $GTD[$tm]      = New-Object 'System.Collections.Generic.HashSet[string]' }
}

$curTeam = $null

foreach ($ln in $lines) {
  $t = ($ln -as [string]).Trim()
  if (-not $t) { continue }

  if ($teamMap.ContainsKey($t)) {
    $curTeam = $teamMap[$t]
    Ensure-Team $curTeam
    continue
  }

  if (-not $curTeam) { continue }

  if ($t -match '^(?<player>.+?)\s+(PG|SG|SF|PF|C)\s+.+?\s+(?<status>Game Time Decision|Out for the season|Expected to be out until at least .+)$') {
    $player = $Matches.player.Trim()
    $status = $Matches.status.Trim()

    if ($status -eq "Game Time Decision") {
      [void]$GTD[$curTeam].Add($player)
    } else {
      [void]$OutLocks[$curTeam].Add($player)
    }
  }
}

Write-Host "`nParsed teams:" -ForegroundColor Yellow
($teamMap.Values | Sort-Object -Unique) | ForEach-Object {
  $tm = $_
  $outCt = if ($OutLocks.ContainsKey($tm)) { $OutLocks[$tm].Count } else { 0 }
  $gtdCt = if ($GTD.ContainsKey($tm)) { $GTD[$tm].Count } else { 0 }

  if (($outCt + $gtdCt) -gt 0) {
    [pscustomobject]@{ Team=$tm; OutLocks=$outCt; GTD=$gtdCt }
  }
} | Format-Table -AutoSize

# ============================
# Build outs per team
# ============================

function Sample-Outs([string]$tm) {
  $outs = New-Object 'System.Collections.Generic.List[string]'

  if ($OutLocks.ContainsKey($tm)) {
    foreach ($p in $OutLocks[$tm]) { $outs.Add($p) }
  }

  if ($GTD.ContainsKey($tm)) {
    foreach ($p in $GTD[$tm]) {
      if ((Get-Random) / [double]::MaxValue -lt $GtdProb) { $outs.Add($p) }
    }
  }

  (($outs | Sort-Object) -join ",")
}

# Run every team in the league (but only if they appear in injuries OR GTD)
$teamsToRun = ($teamMap.Values | Sort-Object -Unique | Where-Object {
  ($OutLocks.ContainsKey($_) -and $OutLocks[$_].Count -gt 0) -or
  ($GTD.ContainsKey($_) -and $GTD[$_].Count -gt 0)
})

if (-not $teamsToRun -or $teamsToRun.Count -eq 0) {
  throw "No teams with injuries parsed from Sim.txt. Team headers may not match teamMap keys."
}

# ============================
# Run scenarios (throttled parallel via ThreadJob)
# ============================

Ensure-ThreadJob

Write-Host "`nRunning sims (Throttle=$Throttle, GTDProb=$GtdProb)..." -ForegroundColor Cyan

$jobs = New-Object 'System.Collections.Generic.List[object]'
$planned = New-Object 'System.Collections.Generic.List[object]'

foreach ($tm in $teamsToRun) {
  $outsRaw = Sample-Outs $tm
  if ([string]::IsNullOrWhiteSpace($outsRaw)) { continue }

  $planned.Add([pscustomobject]@{ Team=$tm; Outs=$outsRaw }) | Out-Null

  Wait-ForJobSlot -limit $Throttle

  $jobs.Add(
    (Start-ThreadJob -Name "sim_$tm" -ArgumentList $tm, $outsRaw, $Stats -ScriptBlock {
      param($team, $outs, $stats)
      python .\tools\dev_role_scenario_dump.py --team $team --outs "$outs" --stats $stats *> $null
      [pscustomobject]@{ Team=$team; Outs=$outs }
    })
  ) | Out-Null
}

Wait-Job -Job $jobs | Out-Null
$results = Receive-Job -Job $jobs
Remove-Job -Job $jobs -Force

Write-Host "Finished initial runs: $($results.Count) teams" -ForegroundColor Green

# ============================
# Post-process: fix name mismatches + build one summary CSV
# ============================

$summary = New-Object 'System.Collections.Generic.List[object]'
$generatedCsvs = New-Object 'System.Collections.Generic.List[string]'

foreach ($r in $results) {
  $tm = $r.Team
  $outsRaw = $r.Outs

  $csvFile = Get-LatestScenarioCsv $tm
  if ($null -eq $csvFile) { continue }

  $generatedCsvs.Add($csvFile.FullName) | Out-Null
  $csv = Import-Csv -LiteralPath $csvFile.FullName

  # If invalid, try rematch outs to roster names and rerun ONCE for this team
  if (Scenario-LooksInvalid $csv) {
    $roster = ($csv | Select-Object -ExpandProperty player -Unique)

    $outsList = $outsRaw -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ }
    $fixed = New-Object 'System.Collections.Generic.List[string]'

    foreach ($o in $outsList) {
      $m = Best-MatchOutName -OutName $o -RosterNames $roster
      if ($m) { $fixed.Add($m) } else { $fixed.Add($o) }
    }

    $outsFixed = ($fixed | Select-Object -Unique) -join ","

    if ($outsFixed -ne $outsRaw) {
      python .\tools\dev_role_scenario_dump.py --team $tm --outs "$outsFixed" --stats $Stats *> $null
      $csvFile = Get-LatestScenarioCsv $tm
      if ($csvFile) {
        $generatedCsvs.Add($csvFile.FullName) | Out-Null
        $csv = Import-Csv -LiteralPath $csvFile.FullName
      }
    }
  }

  # Summary per stat
  $csv |
    Where-Object { $_.stat -in @("PTS","AST","REB") -and [double]$_.role_ctx_removed_budget -gt 0 } |
    Group-Object stat |
    ForEach-Object {
      $g = $_.Group

      $clamped = @($g | Where-Object { [double]$_.role_ctx_guardrails_applied -eq 1 }).Count
      $maxPre  = [math]::Round((@($g | ForEach-Object {[double]$_.role_ctx_mult_pre_guardrails}) | Measure-Object -Maximum).Maximum, 3)
      $maxPost = [math]::Round((@($g | ForEach-Object {[double]$_.role_ctx_mult}) | Measure-Object -Maximum).Maximum, 3)
      $removed = [math]::Round([double]$g[0].role_ctx_removed_budget, 3)
      $outsCt  = [int]$g[0].role_ctx_outs

      $summary.Add([pscustomobject]@{
        team         = $tm
        stat         = $_.Name
        removed      = $removed
        outs_count   = $outsCt
        clamped_rows = $clamped
        max_pre      = $maxPre
        max_post     = $maxPost
        source_csv   = $csvFile.Name
        outs_used    = $outsRaw
      }) | Out-Null
    }
}

$outSummary = Join-Path $DebugDir "league_sim_summary.csv"
$summary | Sort-Object team, stat | Export-Csv -NoTypeInformation -Path $outSummary
Write-Host "`nWrote league summary: $outSummary" -ForegroundColor Green

# ============================
# Cleanup
# ============================

if (-not $KeepCSVs) {
  # Keep latest CSV for each team + the summary; delete older duplicates
  $latestByTeam = @{}
  foreach ($tm in $teamsToRun) {
    $f = Get-LatestScenarioCsv $tm
    if ($f) { $latestByTeam[$f.FullName] = $true }
  }

  foreach ($f in ($generatedCsvs | Select-Object -Unique)) {
    if (-not $latestByTeam.ContainsKey($f)) {
      Remove-Item -LiteralPath $f -Force -ErrorAction SilentlyContinue
    }
  }

  Write-Host "Cleaned up intermediate per-team CSVs (kept latest per team). Use -KeepCSVs to keep everything." -ForegroundColor DarkGreen
}