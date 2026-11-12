param(
  [string]$Group = "all",
  [string]$FromDate = "2024-08-01",
  [string]$ToDate = "2026-11-11",
  [string]$ValidationFrom = "2026-01-01",
  [string]$HoldDays = "2,5,10,15",
  [int]$Shortlist = 40,
  [string]$OutputPrefix = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$outputDir = Join-Path $root "outputs"
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

if (-not $OutputPrefix) {
  $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
  $OutputPrefix = "experimental_combinations_$stamp"
}

$stdout = Join-Path $outputDir "$OutputPrefix.out.log"
$stderr = Join-Path $outputDir "$OutputPrefix.err.log"
$arguments = @(
  "scripts/discover_experimental_combinations.py",
  "--group", $Group,
  "--from-date", $FromDate,
  "--to-date", $ToDate,
  "--validation-from", $ValidationFrom,
  "--hold-days", $HoldDays,
  "--shortlist", $Shortlist,
  "--output-prefix", $OutputPrefix
)

$process = Start-Process -FilePath "D:\Python311\python.exe" -ArgumentList $arguments -WorkingDirectory $root -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru -WindowStyle Hidden

[PSCustomObject]@{
  ProcessId = $process.Id
  OutputPrefix = $OutputPrefix
  StdoutLog = $stdout
  StderrLog = $stderr
  ExpectedCandidateFile = Join-Path $outputDir "$OutputPrefix`_$Group`_*_candidates.csv"
  ExpectedBacktestFile = Join-Path $outputDir "$OutputPrefix`_$Group`_*_backtests.csv"
  ExpectedConfigFile = Join-Path $outputDir "$OutputPrefix`_$Group`_*_config.json"
} | Format-List
