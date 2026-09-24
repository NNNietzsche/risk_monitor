$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonCandidates = @(
    "$env:USERPROFILE/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe",
    (Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue)
)
$runtimePython = $pythonCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
if (-not $runtimePython) { throw 'Install Python 3.11 or newer.' }
& $runtimePython -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
& './.venv/Scripts/python.exe' -m pip install -r backend/requirements.lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& './.venv/Scripts/python.exe' -m pip install -r backend/requirements-sdk.txt
if ($LASTEXITCODE -ne 0) { throw 'SDK dependency installation failed.' }
Write-Host 'Setup complete. Run .\Start.ps1'
