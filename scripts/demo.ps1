<#
.SYNOPSIS
    One-command ProfAssist POC demo for Windows.

.DESCRIPTION
    Copies .env.example to .env when needed, checks that GEMINI_API_KEY is set,
    builds the three app images, starts the stack, and waits for the API.
    It never prints a secret.
#>
$ErrorActionPreference = "Stop"

Push-Location (Join-Path $PSScriptRoot "..")
try {
    if (-not (Test-Path -LiteralPath ".env")) {
        Copy-Item -LiteralPath ".env.example" -Destination ".env"
        Write-Host ""
        Write-Host "Created .env from .env.example." -ForegroundColor Yellow
        Write-Host "Open .env, set GEMINI_API_KEY=your-key, then re-run this script."
        Write-Host "(.env is gitignored - never commit it.)"
        exit 1
    }

    $keyLine = Get-Content -LiteralPath ".env" |
        Where-Object { $_ -match '^GEMINI_API_KEY=' } |
        Select-Object -First 1
    $key = if ($keyLine) { $keyLine.Substring("GEMINI_API_KEY=".Length).Trim() } else { "" }
    if ([string]::IsNullOrWhiteSpace($key)) {
        Write-Host ""
        Write-Host "GEMINI_API_KEY is empty in .env." -ForegroundColor Red
        Write-Host "Open .env, set GEMINI_API_KEY=your-key, then re-run this script."
        exit 1
    }

    Write-Host "> Building app, prefect-runner, frontend..."
    docker compose build app prefect-runner frontend
    if ($LASTEXITCODE -ne 0) { throw "docker compose build failed" }

    Write-Host "> Starting the stack..."
    docker compose up -d --force-recreate
    if ($LASTEXITCODE -ne 0) { throw "docker compose up failed" }

    function Test-Api {
        try {
            $r = Invoke-WebRequest -Uri "http://localhost:8000/api/v1/health" `
                -UseBasicParsing -TimeoutSec 3
            return $r.StatusCode -ge 200 -and $r.StatusCode -lt 300
        } catch {
            return $false
        }
    }

    Write-Host "> Waiting for the API (up to 3 minutes)..."
    $healthy = $false
    for ($i = 0; $i -lt 60; $i++) {
        if (Test-Api) { $healthy = $true; break }
        Write-Host "." -NoNewline
        Start-Sleep -Seconds 3
    }
    Write-Host ""

    if (-not $healthy) {
        Write-Host "API did not become healthy. Run: docker compose logs -f" -ForegroundColor Red
        exit 1
    }

    Write-Host ""
    Write-Host "ProfAssist POC is up:"
    Write-Host "  App:          http://localhost:3000"
    Write-Host "  Register:     http://localhost:3000/register"
    Write-Host "  API:          http://localhost:8000"
    Write-Host "  API docs:     http://localhost:8000/docs"
    Write-Host "  Langfuse:     http://localhost:3100"
    Write-Host "  MLflow:       http://localhost:5000"
    Write-Host "  Prefect:      http://localhost:4200"
    Write-Host "  Moodle mock:  http://localhost:8090/health"
    Write-Host ""
    Write-Host "Register at /register; the first user becomes app admin."
    Write-Host "Moodle is preconfigured against the mock: Test/Sync at"
    Write-Host "  http://localhost:3000/admin/integrations/moodle"
    Write-Host ""
    Write-Host "Logs: docker compose logs -f    Stop: docker compose down"
}
finally {
    Pop-Location
}
