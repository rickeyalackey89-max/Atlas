Set-Location "C:\Users\rick\projects\Atlas"
$python = "C:\Users\rick\projects\Atlas\.venv\Scripts\python.exe"

Write-Output "=== EV Trainer (4-leg + 5-leg) starting at $(Get-Date) ==="
& $python tools/leg_trainer_v5_ev.py --skip "3-leg" 2>&1 | Tee-Object -FilePath "tools\ev_trainer_4leg5leg_output.txt"
Write-Output "=== EV Trainer finished at $(Get-Date) ==="
