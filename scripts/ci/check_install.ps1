# CI: install postloom the way a Windows user does (install.ps1 through iex), then check the
# shortcuts, starting from the Start menu shortcut, an update while it runs and the uninstall.
$ErrorActionPreference = 'Stop'

function Test-Running {
    try { Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/ping' -TimeoutSec 3 | Out-Null; return $true }
    catch { return $false }
}
function Assert([bool] $Condition, [string] $Message) {
    if (-not $Condition) { throw "Check failed: $Message" }
}

Get-Content install.ps1 -Raw | Invoke-Expression
Assert (Test-Running) 'the installer opened postloom'

$Uv = Join-Path $HOME '.local\bin\uv.exe'
if (Get-Command uv -ErrorAction SilentlyContinue) { $Uv = (Get-Command uv).Source }
$Postloom = Join-Path (& $Uv tool dir --bin) 'postloom.exe'
$Links = @(
    (Join-Path ([Environment]::GetFolderPath('Programs')) 'Postloom.lnk'),
    (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Postloom.lnk')
)
foreach ($link in $Links) { Assert (Test-Path $link) "$link exists" }
$Shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($Links[0])
Assert ($Shortcut.TargetPath -like '*pythonw.exe') "the shortcut opens no console window: $($Shortcut.TargetPath)"

& $Postloom open
Assert ($LASTEXITCODE -eq 0) 'a second open finds the running one'

& $Postloom stop
Assert (-not (Test-Running)) 'postloom stopped'
Start-Process -FilePath $Links[0]  # what clicking the icon does
$deadline = (Get-Date).AddSeconds(90)
while (-not (Test-Running) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500 }
Assert (Test-Running) 'the Start menu shortcut started postloom'

Get-Content install.ps1 -Raw | Invoke-Expression  # updating while postloom runs
Assert (Test-Running) 'postloom runs again after the update'

$env:POSTLOOM_UNINSTALL = 1
Get-Content install.ps1 -Raw | Invoke-Expression
Assert (-not (Test-Running)) 'the uninstall stopped postloom'
foreach ($link in $Links) { Assert (-not (Test-Path $link)) "$link is removed" }
Assert (-not (Test-Path $Postloom)) 'postloom.exe is removed'
Assert (Test-Path (Join-Path $HOME 'Postloom\vault')) 'the data is kept'
Write-Host 'All install checks passed.'
