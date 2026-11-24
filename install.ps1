# Install postloom on Windows. In PowerShell (Start menu -> "PowerShell"), paste:
#
#   irm https://raw.githubusercontent.com/mdhabibi/postloom/main/install.ps1 | iex
#
# It installs uv (which brings its own Python, so nothing else is needed), installs
# postloom for this user only, adds Postloom to the Start menu and the desktop and opens it.
# Run it again to update. To remove postloom (your data folder is kept):
#
#   $env:POSTLOOM_UNINSTALL = 1; irm https://raw.githubusercontent.com/mdhabibi/postloom/main/install.ps1 | iex
#
# Nothing here needs administrator rights.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'  # Invoke-WebRequest is much faster without it

# The latest release from PyPI; before the first release, the newest code on GitHub.
$Source = if ($env:POSTLOOM_SOURCE) { $env:POSTLOOM_SOURCE } else {
    try {
        Invoke-WebRequest -UseBasicParsing -Uri 'https://pypi.org/pypi/postloom/json' | Out-Null
        'postloom'
    } catch {
        'https://github.com/mdhabibi/postloom/archive/refs/heads/main.zip'
    }
}
$PythonVersion = if ($env:POSTLOOM_PYTHON) { $env:POSTLOOM_PYTHON } else { '3.12' }

function Fail([string] $Message) {
    Write-Host ''
    Write-Host "postloom could not be installed: $Message" -ForegroundColor Red
    Write-Host 'Copy this message into an issue at https://github.com/mdhabibi/postloom/issues'
    throw 'postloom installation failed'
}

function Find-Uv {
    $command = Get-Command uv -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    foreach ($candidate in @(
            (Join-Path $HOME '.local\bin\uv.exe'),
            (Join-Path $HOME '.cargo\bin\uv.exe'))) {
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

function Invoke-Quietly([scriptblock] $Run) {
    # Windows PowerShell turns a redirected native error stream into an exception.
    try { & $Run *> $null } catch { }
}

function Invoke-Checked([string] $What) {
    if ($LASTEXITCODE -ne 0) { Fail $What }
}

$Uv = Find-Uv

if ($env:POSTLOOM_UNINSTALL) {
    Remove-Item Env:\POSTLOOM_UNINSTALL
    if (-not $Uv) { Fail "uv isn't installed, so neither is postloom." }
    $Bin = & $Uv tool dir --bin
    $Postloom = Join-Path $Bin 'postloom.exe'
    if (Test-Path $Postloom) {
        Invoke-Quietly { & $Postloom stop }
        & $Postloom shortcut --remove
    }
    & $Uv tool uninstall postloom
    Invoke-Checked "uv couldn't remove postloom."
    Write-Host ''
    Write-Host 'postloom is removed. Your data is still in your Postloom folder (in your user folder);'
    Write-Host 'delete that folder yourself if you no longer want it.'
    return
}

Write-Host 'Installing postloom. This takes a minute or two the first time.'
Write-Host ''

if (-not $Uv) {
    Write-Host '1/3  Installing uv, which installs and updates postloom and its Python...'
    try {
        $installer = Invoke-RestMethod -Uri 'https://astral.sh/uv/install.ps1'
    } catch {
        Fail "uv couldn't be downloaded. Check your internet connection and try again."
    }
    $env:UV_PRINT_QUIET = '1'
    & ([scriptblock]::Create($installer))
    $Uv = Find-Uv
    if (-not $Uv) { Fail "uv was installed but can't be found. Open a new PowerShell and try again." }
} else {
    Write-Host '1/3  uv is already installed.'
}

Write-Host "2/3  Installing postloom (and Python $PythonVersion if needed)..."
$Bin = & $Uv tool dir --bin
$Postloom = Join-Path $Bin 'postloom.exe'
if (Test-Path $Postloom) {
    # Windows can't replace the files of a running program, so stop it first.
    Invoke-Quietly { & $Postloom stop }
}
& $Uv tool install --quiet --force --python $PythonVersion `
    --refresh-package postloom --reinstall-package postloom $Source
Invoke-Checked "uv couldn't install postloom. Check your internet connection and try again."
Invoke-Quietly { & $Uv tool update-shell }
if (-not (Test-Path $Postloom)) { Fail "postloom was installed but $Postloom is missing." }

Write-Host '3/3  Adding Postloom to the Start menu and the desktop...'
& $Postloom shortcut
if ($LASTEXITCODE -ne 0) { Write-Host '     (No shortcut this time; you can still type: postloom open)' }

Write-Host ''
Write-Host 'Done. postloom is opening in your browser.'
Write-Host 'Next time, open it from the Postloom icon, or type: postloom open'
Write-Host ''
& $Postloom open
Invoke-Checked "postloom was installed but didn't start."
