# Registers Tarbiyah Hub to start automatically when you log in to Windows,
# and to restart automatically if it stops unexpectedly.
# Run once:  right-click this file > "Run with PowerShell"
# Remove:    Unregister-ScheduledTask -TaskName "TarbiyahHub" -Confirm:$false
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$pyw = Join-Path $root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pyw)) { Write-Host "Run install.bat first."; exit 1 }
$action = New-ScheduledTaskAction -Execute $pyw -Argument "-m tarbiyah run" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Days 3650) `
  -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "TarbiyahHub" -Action $action -Trigger $trigger -Settings $settings `
  -Description "Tarbiyah Hub worker + dashboard (http://127.0.0.1:8000)" -Force | Out-Null
Start-ScheduledTask -TaskName "TarbiyahHub"
Write-Host "Done. Tarbiyah Hub now starts at logon (no console windows). Open http://127.0.0.1:8000"
