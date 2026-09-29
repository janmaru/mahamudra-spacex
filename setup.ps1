# Crea il venv e installa le dipendenze (rich-ui compreso, da GitHub).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed (exit $LASTEXITCODE)" }
}

# I venv creati dalla versione precedente collegavano rich-ui con un .pth locale:
# va rimosso prima di pip, altrimenti pip può considerare rich-ui già installato.
$sitePackages = & .\.venv\Scripts\python.exe -c "import sysconfig; print(sysconfig.get_paths()['purelib'])"
if ($LASTEXITCODE -ne 0 -or -not $sitePackages) { throw "Could not determine the venv site-packages" }
Remove-Item (Join-Path $sitePackages "rich_ui_local.pth") -ErrorAction SilentlyContinue

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed (exit $LASTEXITCODE)" }

& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "requirements installation failed (exit $LASTEXITCODE)" }

Write-Host "Start: .\.venv\Scripts\Activate.ps1 ; python .\main.py"
