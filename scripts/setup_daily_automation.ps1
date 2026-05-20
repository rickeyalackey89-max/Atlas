# Setup Daily Graphics Task - Run this once to install the automation
# ================================================================

Write-Host "🎯 Setting up daily Atlas graphics automation..."

try {
    # Task details
    $TaskName = "Atlas Daily Graphics Generation"
    $ScriptPath = "C:\Users\13142\Atlas\NBA\scripts\task_8am_graphics.ps1"
    $WorkingDir = "C:\Users\13142\Atlas\NBA"
    
    # Create task components
    $Action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-ExecutionPolicy Bypass -File `"$ScriptPath`"" -WorkingDirectory $WorkingDir
    $Trigger = New-ScheduledTaskTrigger -Daily -At '8:00 AM'
    $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
    $Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
    
    # Create and register task
    $Task = New-ScheduledTask -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Description "Daily Atlas graphics generation for subscribers (8:00 AM)"
    
    # Remove existing task if it exists
    try {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    } catch {}
    
    # Register new task
    Register-ScheduledTask -TaskName $TaskName -InputObject $Task
    
    Write-Host "✅ Task registered successfully!"
    Write-Host "📅 Schedule: Daily at 8:00 AM"
    Write-Host "📍 Script: $ScriptPath"
    
    # Test the task
    Write-Host "`n🧪 Testing task execution..."
    Start-ScheduledTask -TaskName $TaskName
    
    Write-Host "`n✅ Setup complete! Your daily graphics will be generated automatically at 8:00 AM."
    Write-Host "🎨 Graphics will be saved to: C:\Users\13142\Atlas\NBA\data\output\graphics\"
    
    # Show task details
    Write-Host "`n📋 Task Details:"
    Get-ScheduledTask -TaskName $TaskName | Format-List TaskName, State, NextRunTime
    
} catch {
    Write-Host "❌ Error setting up task: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "💡 You may need to run PowerShell as Administrator" -ForegroundColor Yellow
}
