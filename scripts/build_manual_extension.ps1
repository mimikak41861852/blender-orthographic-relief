param(
    [string]$BlenderPath = "blender",
    [string]$Version = "1.4.0"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Source = Join-Path $RepoRoot "blender_extension\orthographic_relief"
$Dist = Join-Path $RepoRoot "dist"
$Output = Join-Path $Dist "orthographic_relief-$Version.zip"
$ChecksumOutput = "$Output.sha256"

if (Test-Path -LiteralPath $BlenderPath) {
    $BlenderExecutable = (Resolve-Path -LiteralPath $BlenderPath).Path
} else {
    $BlenderCommand = Get-Command $BlenderPath -ErrorAction SilentlyContinue
    if ($null -eq $BlenderCommand) {
        throw "Blender was not found. Add blender to PATH or pass -BlenderPath with the full path to blender.exe."
    }
    $BlenderExecutable = $BlenderCommand.Source
}

New-Item -ItemType Directory -Force -Path $Dist | Out-Null
& $BlenderExecutable --command extension validate $Source
if ($LASTEXITCODE -ne 0) {
    throw "Extension source validation failed"
}

if (Test-Path -LiteralPath $Output) {
    Remove-Item -LiteralPath $Output
}
& $BlenderExecutable --command extension build --source-dir $Source --output-filepath $Output
if ($LASTEXITCODE -ne 0) {
    throw "Extension build failed"
}

& $BlenderExecutable --command extension validate $Output
if ($LASTEXITCODE -ne 0) {
    throw "Extension package validation failed"
}

$Hash = Get-FileHash -Algorithm SHA256 -LiteralPath $Output
$ChecksumLine = "$($Hash.Hash.ToLowerInvariant())  $(Split-Path -Leaf $Output)"
Set-Content -LiteralPath $ChecksumOutput -Value $ChecksumLine -Encoding ASCII
Write-Host "Created $Output"
Write-Host "Created $ChecksumOutput"
Write-Host "SHA256 $($Hash.Hash.ToLowerInvariant())"
