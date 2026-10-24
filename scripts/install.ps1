param(
    [string]$BlenderPath = "C:\Program Files\Blender Foundation\Blender 3.6\blender.exe",
    [switch]$SkipPythonEnvironment,
    [switch]$SkipAddon
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Dist = Join-Path $RepoRoot "dist"
$Tools = Join-Path $RepoRoot ".tools"
$Uv = Join-Path $Tools "uv\uv.exe"

New-Item -ItemType Directory -Force -Path $Dist, $Tools | Out-Null

if (-not $SkipPythonEnvironment) {
    if (-not (Test-Path -LiteralPath $Uv)) {
        throw "uv is missing at $Uv. Run the documented bootstrap command first."
    }
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $Tools "python"
    & $Uv python install 3.11
    & $Uv venv --python 3.11 (Join-Path $RepoRoot ".venv")
    & $Uv pip install --python (Join-Path $RepoRoot ".venv\Scripts\python.exe") -e $RepoRoot
}

if (-not $SkipAddon) {
    if (-not (Test-Path -LiteralPath $BlenderPath)) {
        throw "Blender was not found at $BlenderPath"
    }
    $AddonZip = Join-Path $Dist "relief_mcp.zip"
    if (Test-Path -LiteralPath $AddonZip) {
        Remove-Item -LiteralPath $AddonZip
    }
    Compress-Archive -Path (Join-Path $RepoRoot "blender_addon\relief_mcp") -DestinationPath $AddonZip
    & $BlenderPath --background --factory-startup --python (Join-Path $RepoRoot "scripts\install_addon.py") -- $AddonZip
}

Write-Host "Relief MCP environment is ready."
