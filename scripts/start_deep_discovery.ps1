param(
  [string]$FromDate = "2026-06-01",
  [string]$ToDate = "2026-09-04",
  [string]$Group = "all",
  [string]$HoldDays = "5,10,15,21",
  [string]$OutputPrefix = "",
  [int]$MaxAtomsForPairs = 60,
  [int]$MaxPairsForTriples = 400
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

if (-not $OutputPrefix) {
  $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
  $OutputPrefix = "deep_discovery_$stamp"
}

$outputDir = Join-Path $root "outputs"
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

$stdout = Join-Path $outputDir "$OutputPrefix.out.log"
$stderr = Join-Path $outputDir "$OutputPrefix.err.log"

$arguments = @(
  "scripts/discover_rules_from_filters.py",
  "--from-date", $FromDate,
  "--to-date", $ToDate,
  "--group", $Group,
  "--hold-days", $HoldDays,
  "--output-prefix", $OutputPrefix,
  "--max-atoms-for-pairs", $MaxAtomsForPairs,
  "--max-pairs-for-triples", $MaxPairsForTriples
)

$process = Start-Process -FilePath "python" -ArgumentList $arguments -WorkingDirectory $root -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru -WindowStyle Hidden

[PSCustomObject]@{
  ProcessId = $process.Id
  OutputPrefix = $OutputPrefix
  StdoutLog = $stdout
  StderrLog = $stderr
  AtomsCsv = Join-Path $outputDir "$OutputPrefix`_atoms.csv"
  PairsCsv = Join-Path $outputDir "$OutputPrefix`_pairs.csv"
  TriplesCsv = Join-Path $outputDir "$OutputPrefix`_triples.csv"
  BacktestsCsv = Join-Path $outputDir "$OutputPrefix`_backtests.csv"
} | Format-List
