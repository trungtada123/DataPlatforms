param(
    [string]$SourceDir = "D:\LandingAI\parsed_output",
    [string]$DestinationDir = "data\financial_reports\parsed_output"
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$resolvedSource = (Resolve-Path $SourceDir).Path
$resolvedDestination = Join-Path $repoRoot $DestinationDir

if (-not (Test-Path -Path $resolvedSource)) {
    throw "Khong tim thay parsed_output nguon tai: $resolvedSource"
}

New-Item -ItemType Directory -Force -Path $resolvedDestination | Out-Null

Write-Host "== Sync parsed_output ==" -ForegroundColor Cyan
Write-Host "Source      : $resolvedSource"
Write-Host "Destination : $resolvedDestination"

Copy-Item -Path (Join-Path $resolvedSource "*") -Destination $resolvedDestination -Recurse -Force

$copiedFolders = (Get-ChildItem -Path $resolvedDestination -Directory -ErrorAction SilentlyContinue | Measure-Object).Count
$copiedFiles = (Get-ChildItem -Path $resolvedDestination -File -Recurse -ErrorAction SilentlyContinue | Measure-Object).Count

Write-Host "Da copy xong parsed_output." -ForegroundColor Green
Write-Host "Folders: $copiedFolders"
Write-Host "Files  : $copiedFiles"
Write-Host "Luu y: thu muc nay da duoc ignore trong git, chi dung local/dev."
