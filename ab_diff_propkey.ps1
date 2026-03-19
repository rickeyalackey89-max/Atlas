# ===== A/B diff by prop_key (safe, no parser gotchas) =====

param(
  [string]$RoleCsv = "C:\Users\rick\projects\Atlas\data\output\runs\20260219_182908\role_on.csv",
  [string]$NoCsv   = "C:\Users\rick\projects\Atlas\data\output\runs\20260219_182551\no_role.csv"
)

$role = @(Import-Csv -LiteralPath $RoleCsv)
$no   = @(Import-Csv -LiteralPath $NoCsv)

if($role.Count -eq 0){ throw "Role CSV empty: $RoleCsv" }
if($no.Count   -eq 0){ throw "No CSV empty:   $NoCsv" }

# Validate required cols
foreach($c in @("prop_key","p","p_adj","role_ctx_mult")){
  if(-not ($role[0].PSObject.Properties.Name -contains $c)){ throw "Role missing column: $c" }
  if(-not ($no[0].PSObject.Properties.Name   -contains $c)){ throw "No   missing column: $c" }
}

# Index no-role by prop_key
$noBy = @{}
foreach($r in $no){
  $k = [string]$r.prop_key
  if($k -and -not $noBy.ContainsKey($k)){ $noBy[$k] = $r }
}

# Build diffs
$diff = New-Object System.Collections.Generic.List[object]
foreach($r in $role){
  $k = [string]$r.prop_key
  if(-not $k){ continue }
  $o = $noBy[$k]
  if($null -eq $o){ continue }

  $pRole  = [double]$r.p
  $pNo    = [double]$o.p
  $paRole = [double]$r.p_adj
  $paNo   = [double]$o.p_adj
  $rmRole = [double]$r.role_ctx_mult
  $rmNo   = [double]$o.role_ctx_mult

  $diff.Add([pscustomobject]@{
    prop_key = $k
    d_p      = $pRole - $pNo
    d_p_adj  = $paRole - $paNo
    d_role   = $rmRole - $rmNo
    d_gap    = ($paRole - $pRole) - ($paNo - $pNo)   # change in (p_adj - p)
  })
}

Write-Host ("Matched by prop_key: {0} / role={1} no={2}" -f $diff.Count, $role.Count, $no.Count)

function Summ([object[]]$rows, [string]$col){
  $vals = @($rows | ForEach-Object { $_.$col } | ForEach-Object { [double]$_ } | Sort-Object)
  if($vals.Count -eq 0){
    Write-Host ("{0}: (no data)" -f $col)
    return
  }
  $n = $vals.Count
  $p50 = $vals[[int][math]::Floor(($n-1)*0.50)]
  $p90 = $vals[[int][math]::Floor(($n-1)*0.90)]
  $p99 = $vals[[int][math]::Floor(($n-1)*0.99)]
  Write-Host ("{0}: min={1:n6} p50={2:n6} p90={3:n6} p99={4:n6} max={5:n6} n={6}" -f $col,$vals[0],$p50,$p90,$p99,$vals[-1],$n)
}

Summ $diff "d_p"
Summ $diff "d_p_adj"
Summ $diff "d_role"
Summ $diff "d_gap"

# Extra: prove whether NO run is truly role-off (should be ~all 1.0)
$noNon1 = @($no | Where-Object { [double]$_.role_ctx_mult -ne 1.0 }).Count
Write-Host ("NO non-1 role_ctx_mult count = {0} / {1}" -f $noNon1, $no.Count)
