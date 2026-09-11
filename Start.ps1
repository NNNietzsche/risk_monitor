$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath './.venv/Scripts/python.exe')) { throw 'Run .\Setup.ps1 first.' }
if (Test-Path -LiteralPath '.env') {
    foreach ($line in Get-Content -LiteralPath '.env' -Encoding UTF8) {
        if ($line -match '^\s*(RISK_DB_PATH|RISK_POLL_SECONDS|AI_API_KEY|AI_BASE_URL|AI_MODEL)\s*=(.*)$') {
            [Environment]::SetEnvironmentVariable($matches[1], $matches[2].Trim().Trim('"').Trim("'"), 'Process')
        }
    }
}
if (-not $env:RISK_POLL_SECONDS) { $env:RISK_POLL_SECONDS = '30' }
Write-Host 'Open http://127.0.0.1:8000/asset-risk.html - Ctrl+C to stop.'
& './.venv/Scripts/python.exe' -m uvicorn backend.app:create_app --factory --host 127.0.0.1 --port 8000
