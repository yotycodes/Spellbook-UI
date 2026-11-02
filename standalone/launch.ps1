# Spellbook launcher — Windows (PowerShell).
#
#   .\launch.ps1              app mode: a desktop window
#   .\launch.ps1 -Web         web mode: server only; open http://127.0.0.1:7872 in your browser
#   .\launch.ps1 -Port N      custom port (default 7872)
#
# First run: creates .venv and installs the pinned requirements (Python 3.10+ required;
# get it from python.org and tick "Add to PATH", or use "py").
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $Here ".venv"
$Py = Join-Path $Venv "Scripts\python.exe"

$PyBin = $null
foreach ($c in @("py", "python3", "python")) {
  if (Get-Command $c -ErrorAction SilentlyContinue) { $PyBin = $c; break }
}
if (-not $PyBin) {
  Write-Error "Python 3.10+ is required. Install it from python.org and tick 'Add python.exe to PATH'."
  exit 1
}

if (-not (Test-Path $Py)) {
  Write-Host "First run: creating Spellbook's Python environment (one time, a few minutes)..."
  & $PyBin -m venv $Venv
  & $Py -m pip install --upgrade pip --quiet
  & $Py -m pip install -r (Join-Path $Here "requirements.txt")
  Write-Host "Environment ready."
}

$env:PYTHONDONTWRITEBYTECODE = "1"
$Port = "7872"
$Web = $false
for ($i = 0; $i -lt $args.Count; $i++) {
  switch ($args[$i]) {
    "-Web"  { $Web = $true }
    "-Port" { $i++; $Port = $args[$i] }
    default { Write-Error "Unknown option $($args[$i]) (use -Web or -Port N)"; exit 2 }
  }
}
$env:SPELLBOOK_PORT = $Port

if ($Web) {
  & $Py (Join-Path $Here "server.py") --no-window --port $Port
} else {
  & $Py (Join-Path $Here "server.py") --window --port $Port
}
