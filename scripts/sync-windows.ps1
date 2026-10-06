[CmdletBinding()]
param(
    [switch]$Apply,
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$TargetHome = $env:USERPROFILE,
    [string]$CodexHome = $env:CODEX_HOME,
    [string]$Python = 'python'
)

$ErrorActionPreference = 'Stop'
if (-not [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform([System.Runtime.InteropServices.OSPlatform]::Windows)) {
    throw 'This entry point is for native Windows. Use Python directly or Stow on Linux.'
}
$arguments = @((Join-Path $PSScriptRoot 'sync-codex.py'), '--repo', $RepoRoot, '--home', $TargetHome)
if ($CodexHome) { $arguments += @('--codex-home', $CodexHome) }
if ($Apply) { $arguments += '--apply' }
& $Python @arguments
if ($LASTEXITCODE -ne 0) { throw 'Codex sync failed. Python 3.11+ and Windows Developer Mode (or administrator rights) are required.' }
