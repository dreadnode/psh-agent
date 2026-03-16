<#
.SYNOPSIS
    Configure the Windows target VM with Git and Claude Code.
#>
$ErrorActionPreference = "Stop"

# ── Install Git for Windows ────────────────────────────────────
Write-Host "[+] Installing Git for Windows..."
$gitInstaller = "$env:TEMP\git-installer.exe"
Invoke-WebRequest -Uri "https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.2/Git-2.47.1.2-64-bit.exe" -OutFile $gitInstaller
Start-Process -FilePath $gitInstaller -ArgumentList "/VERYSILENT", "/NORESTART", "/NOCANCEL", "/SP-", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS" -Wait
Remove-Item $gitInstaller -ErrorAction SilentlyContinue

# Refresh PATH so git is available immediately
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
Write-Host "[+] Git version: $(git --version)"

# ── Install Claude Code ────────────────────────────────────────
Write-Host "[+] Installing Claude Code..."
irm https://claude.ai/install.ps1 | iex

# Add Claude to PATH (installer doesn't do this automatically)
$claudeBin = "$env:USERPROFILE\.local\bin"
if ($env:Path -notlike "*$claudeBin*") {
    [Environment]::SetEnvironmentVariable("Path", $env:Path + ";$claudeBin", "User")
    $env:Path += ";$claudeBin"
}
Write-Host "[+] Claude version: $(claude --version)"

Write-Host "[+] Done"
