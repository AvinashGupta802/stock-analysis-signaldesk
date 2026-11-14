param(
  [switch]$Incremental,
  [switch]$Rebuild,
  [switch]$ExportParquet,
  [string]$FromDate = "2024-07-08",
  [string]$ToDate = "",
  [string]$Symbols = "",
  [string]$OutputPrefix = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$outputDir = Join-Path $root "outputs"
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
if (-not $OutputPrefix) {
  $OutputPrefix = "feature_store_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
}

$stdout = Join-Path $outputDir "$OutputPrefix.out.log"
$stderr = Join-Path $outputDir "$OutputPrefix.err.log"
$arguments = @("scripts/build_feature_store.py", "--from-date", $FromDate)
if ($ToDate) { $arguments += @("--to-date", $ToDate) }
if ($Symbols) { $arguments += @("--symbols", $Symbols) }
if ($Incremental) { $arguments += "--incremental" }
if ($Rebuild) { $arguments += "--rebuild" }
if ($ExportParquet) { $arguments += "--export-parquet" }

$process = Start-Process -FilePath "D:\Python311\python.exe" -ArgumentList $arguments -WorkingDirectory $root -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru -WindowStyle Hidden

[PSCustomObject]@{
  ProcessId = $process.Id
  StdoutLog = $stdout
  StderrLog = $stderr
  DuckDbStore = Join-Path $root "data\stock_feature_store.duckdb"
  ParquetDirectory = Join-Path $root "data\feature_store_parquet"
} | Format-List
