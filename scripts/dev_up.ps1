<#
.SYNOPSIS
  VigilZone — start ALL services locally (no Docker).
.DESCRIPTION
  Launches Django (:8000), AI module (:8080) and Vite UI (:5000)
  as background jobs. Press Ctrl+C to stop everything.
.EXAMPLE
  .\scripts\dev_up.ps1          # run from repo root
#>

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Definition)

# ── Resolve Python ────────────────────────────────────────────
$PyExe = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $PyExe)) {
    $PyExe = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $PyExe) {
        Write-Error "Python not found. Create a .venv or install Python."
        exit 1
    }
}
Write-Host "[dev_up] Using Python: $PyExe" -ForegroundColor Cyan

# ── Helper: start a background job with label ─────────────────
$Jobs = @()

function Start-Service {
    param([string]$Name, [string]$WorkDir, [scriptblock]$Block)
    Write-Host "[dev_up] Starting $Name …" -ForegroundColor Cyan
    $j = Start-Job -Name $Name -ScriptBlock $Block -ArgumentList $PyExe, $WorkDir, $Root
    $script:Jobs += $j
}

# ── 1. Django backend (port 8000) ─────────────────────────────
Start-Service -Name "django" -WorkDir "$Root\services\backend" -Block {
    param($Py, $Dir, $Rt)
    Set-Location $Dir
    & $Py manage.py migrate --noinput 2>&1
    & $Py manage.py runserver 0.0.0.0:8000 2>&1
}

# ── 2. AI module (port 8080) ─────────────────────────────────
Start-Service -Name "ai" -WorkDir "$Root\services\ai" -Block {
    param($Py, $Dir, $Rt)
    Set-Location $Dir
    & $Py run.py 2>&1
}

# ── 3. UI dev server (port 5000) ─────────────────────────────
Start-Service -Name "ui" -WorkDir "$Root\web\ui" -Block {
    param($Py, $Dir, $Rt)
    Set-Location $Dir
    npm install --silent 2>&1
    npm run dev 2>&1
}

# ── Print info ────────────────────────────────────────────────
Write-Host ""
Write-Host "[dev_up] All services starting…" -ForegroundColor Green
Write-Host ""
Write-Host "  Web UI:   http://localhost:5000"
Write-Host "  API:      http://localhost:8000/api/"
Write-Host "  AI:       http://localhost:8080"
Write-Host ""
Write-Host "[dev_up] Press Ctrl+C to stop all." -ForegroundColor Cyan
Write-Host ""

# ── Tail output and wait ─────────────────────────────────────
try {
    while ($true) {
        foreach ($j in $Jobs) {
            Receive-Job -Job $j -ErrorAction SilentlyContinue | ForEach-Object {
                Write-Host "  [$($j.Name)] $_"
            }
        }
        Start-Sleep -Milliseconds 500

        # If any job stopped unexpectedly, report it
        foreach ($j in $Jobs) {
            if ($j.State -eq "Failed") {
                Write-Host "[dev_up] $($j.Name) FAILED:" -ForegroundColor Red
                Receive-Job -Job $j -ErrorAction SilentlyContinue | ForEach-Object {
                    Write-Host "  $_" -ForegroundColor Red
                }
            }
        }
    }
}
finally {
    Write-Host "`n[dev_up] Shutting down…" -ForegroundColor Yellow
    $Jobs | ForEach-Object {
        Stop-Job -Job $_ -ErrorAction SilentlyContinue
        Remove-Job -Job $_ -Force -ErrorAction SilentlyContinue
    }
    Write-Host "[dev_up] Done." -ForegroundColor Green
}
