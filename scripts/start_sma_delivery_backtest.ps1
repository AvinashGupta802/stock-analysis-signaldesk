param(
  [string]$Group = "nifty500",
  [string]$FromDate = "2026-06-01",
  [string]$ToDate = "2026-11-11",
  [string]$ValidationFrom = "2026-09-15",
  [string]$HoldDays = "2,5,10,15",
  [int]$Shortlist = 60,
  [string]$OutputPrefix = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$outputDir = Join-Path $root "outputs"
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
if (-not $OutputPrefix) {
  $OutputPrefix = "sma_delivery_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
}

$stdout = Join-Path $outputDir "$OutputPrefix.out.log"
$stderr = Join-Path $outputDir "$OutputPrefix.err.log"
$arguments = @(
  "scripts/backtest_sma_delivery_hypotheses.py",
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
  ExpectedCandidates = Join-Path $outputDir "$OutputPrefix`_$Group`_*_candidates.csv"
  ExpectedBacktests = Join-Path $outputDir "$OutputPrefix`_$Group`_*_backtests.csv"
  ExpectedConfig = Join-Path $outputDir "$OutputPrefix`_$Group`_*_config.json"
} | Format-List
