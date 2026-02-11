# Extracted into module Private/
# Source: live_feed_publish.ps1:4-10
function Banner([string]$t) {
  $ts = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
  Write-Host ""
  Write-Host "==============================="
  Write-Host "[$t] $ts"
  Write-Host "==============================="
}

