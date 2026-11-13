# Build dist\Gerber2Graphtec.exe  (run from the project folder)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path .venv)) {
    python -m venv .venv
}
& .\.venv\Scripts\python -m pip install -q --upgrade pip
& .\.venv\Scripts\python -m pip install -q -e ".[dev]"
& .\.venv\Scripts\python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "tests failed" }
& .\.venv\Scripts\python -m PyInstaller --noconfirm --clean Gerber2Graphtec.spec
if ($LASTEXITCODE -ne 0) { throw "build failed" }
Get-Item dist\Gerber2Graphtec.exe | Select-Object Name, @{n = "MB"; e = { [math]::Round($_.Length / 1MB, 1) } }, @{n = "Version"; e = { $_.VersionInfo.ProductVersion } }
