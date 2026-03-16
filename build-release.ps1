param(
    [string]$Python = "python",
    [string]$PyInstaller = "pyinstaller",
    [string]$Iscc = "iscc",
    [switch]$SkipDependencyInstall
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host "Cleaning previous build output..."
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue

if (-not $SkipDependencyInstall) {
    Write-Host "Installing Python dependencies..."
    & $Python -m pip install -r requirements.txt pyinstaller
}

Write-Host "Building application bundle..."
& $PyInstaller --noconfirm --clean KeytoXboxPS.spec

if (-not (Get-Command $Iscc -ErrorAction SilentlyContinue)) {
    throw "Inno Setup compiler not found. Install Inno Setup 6 and make sure 'iscc' is available on PATH."
}

Write-Host "Building installer..."
& $Iscc ".\KeytoXboxPS.iss"

Write-Host "Release artifacts:"
Write-Host "  App bundle: dist\\KeytoXboxPS"
Write-Host "  Installer:   dist\\installer"
