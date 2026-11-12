param(
    [string]$Group = "all",
    [string]$FromDate = "2024-08-01",
    [string]$ToDate = "2026-11-11",
    [string]$ValidationFrom = "2026-01-01"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = "D:\Python311\python.exe"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$outputDir = Join-Path $root "outputs"
$logPath = Join-Path $outputDir "experimental_setups_${Group}_${timestamp}.out.log"

New-Item -ItemType Directory -Path $outputDir -Force | Out-Null

$arguments = @(
    (Join-Path $PSScriptRoot "deep_backtest_experimental_setups.py"),
    "--group", $Group,
    "--from-date", $FromDate,
    "--to-date", $ToDate,
    "--validation-from", $ValidationFrom,
    "--hold-days", "2,5,10,15,20,30",
    "--targets", "5,10,15",
    "--stops", "5,7,10",
    "--output-prefix", "experimental_setups"
)

$process = Start-Process -FilePath $python `
    -ArgumentList $arguments `
    -WorkingDirectory $root `
    -RedirectStandardOutput $logPath `
    -RedirectStandardError ($logPath + ".err") `
    -WindowStyle Hidden `
    -PassThru

Write-Output "Experimental deep backtest started."
Write-Output "Process ID: $($process.Id)"
Write-Output "Progress log: $logPath"
Write-Output "Results folder: $outputDir"
