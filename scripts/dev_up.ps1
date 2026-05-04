<#
.SYNOPSIS
  VigilZone — start local services in the supported MediaMTX-first order.
.DESCRIPTION
  Starts MediaMTX, waits for its control API, then launches Django (:8000),
  AI (:8001), the local worker node, and the Vite UI (:5000) as background jobs.
  Press Ctrl+C to stop everything.
.EXAMPLE
  .\scripts\dev_up.ps1
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

# ── Resolve MediaMTX ──────────────────────────────────────────
$MediaMtxExeCandidates = @(
    $env:MEDIAMTX_EXE,
    (Join-Path $Root "tools\mediamtx.exe"),
    "C:\tools\mediamtx.exe"
) | Where-Object { $_ }

$MediaMtxExe = $MediaMtxExeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $MediaMtxExe) {
    Write-Error "MediaMTX executable not found. Set MEDIAMTX_EXE or place mediamtx.exe in C:\tools."
    exit 1
}

$MediaMtxConfigCandidates = @(
    $env:MEDIAMTX_CONFIG_PATH,
    (Join-Path $Root "tools\mediamtx.yml"),
    "C:\tools\mediamtx.yml"
) | Where-Object { $_ }

$MediaMtxConfig = $MediaMtxConfigCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $MediaMtxConfig) {
    Write-Error "MediaMTX config not found. Set MEDIAMTX_CONFIG_PATH or place mediamtx.yml in C:\tools."
    exit 1
}

$MediaMtxApiBase = if ($env:MEDIAMTX_API_URL) { $env:MEDIAMTX_API_URL.TrimEnd('/') } else { "http://127.0.0.1:9997" }

# ── Helper: start a background job with label ─────────────────
$Jobs = @()

function Start-Service {
    param([string]$Name, [string]$WorkDir, [scriptblock]$Block, [object[]]$ArgumentList = @())
    Write-Host "[dev_up] Starting $Name ..." -ForegroundColor Cyan
    $args = @($PyExe, $WorkDir, $Root) + $ArgumentList
    $j = Start-Job -Name $Name -ScriptBlock $Block -ArgumentList $args
    $script:Jobs += $j
}

function Wait-HttpReady {
    param(
        [string]$Name,
        [string]$Url,
        [int]$TimeoutSeconds = 60
    )

    Write-Host "[dev_up] Waiting for $Name at $Url ..." -ForegroundColor Cyan
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500) {
                Write-Host "[dev_up] $Name is ready." -ForegroundColor Green
                return
            }
        } catch {
        }
        Start-Sleep -Seconds 2
    }
    throw "$Name did not become ready within $TimeoutSeconds seconds."
}

# ── 1. MediaMTX (control plane first) ─────────────────────────
Start-Service -Name "mediamtx" -WorkDir (Split-Path -Parent $MediaMtxExe) -ArgumentList @($MediaMtxExe, $MediaMtxConfig) -Block {
    param($Py, $Dir, $Rt, $ExePath, $ConfigPath)
    Set-Location $Dir
    & $ExePath $ConfigPath 2>&1
}

Wait-HttpReady -Name "MediaMTX" -Url "$MediaMtxApiBase/v3/config/global/get" -TimeoutSeconds 60

# ── 2. Django backend (port 8000) ─────────────────────────────
Start-Service -Name "django" -WorkDir "$Root\services\backend" -Block {
    param($Py, $Dir, $Rt)
    Set-Location $Dir
    & $Py manage.py migrate --noinput 2>&1
    & $Py manage.py runserver 0.0.0.0:8000 2>&1
}

Wait-HttpReady -Name "Django" -Url "http://127.0.0.1:8000/admin/login/" -TimeoutSeconds 90

# ── 3. AI module (port 8001) ──────────────────────────────────
Start-Service -Name "ai" -WorkDir "$Root\services\ai" -Block {
    param($Py, $Dir, $Rt)
    Set-Location $Dir
    & $Py run.py 2>&1
}

Wait-HttpReady -Name "AI" -Url "http://127.0.0.1:8001/health" -TimeoutSeconds 90

# ── 4. Unified worker node (local dev only) ───────────────────
Start-Service -Name "worker" -WorkDir "$Root\services\backend" -Block {
    param($Py, $Dir, $Rt)
    Set-Location $Dir
    & $Py manage.py run_worker_node 2>&1
}

# ── 5. UI dev server (port 5000) ──────────────────────────────
Start-Service -Name "ui" -WorkDir "$Root\web\ui" -Block {
    param($Py, $Dir, $Rt)
    Set-Location $Dir
    npm install --silent 2>&1
    npm run dev 2>&1
}

# ── Print info ────────────────────────────────────────────────
Write-Host ""
Write-Host "[dev_up] All services starting in supported local order..." -ForegroundColor Green
Write-Host ""
Write-Host "  MediaMTX: $MediaMtxApiBase"
Write-Host "  Web UI:   http://localhost:5000"
Write-Host "  API:      http://localhost:8000/api/"
Write-Host "  AI:       http://localhost:8001"
Write-Host "  Worker:   python manage.py run_worker_node"
Write-Host ""
Write-Host "[dev_up] Press Ctrl+C to stop all." -ForegroundColor Cyan
Write-Host ""

# ── Tail output and wait ──────────────────────────────────────
try {
    while ($true) {
        foreach ($j in $Jobs) {
            Receive-Job -Job $j -ErrorAction SilentlyContinue | ForEach-Object {
                Write-Host "  [$($j.Name)] $_"
            }
        }
        Start-Sleep -Milliseconds 500

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
    Write-Host "`n[dev_up] Shutting down..." -ForegroundColor Yellow
    $Jobs | ForEach-Object {
        Stop-Job -Job $_ -ErrorAction SilentlyContinue
        Remove-Job -Job $_ -Force -ErrorAction SilentlyContinue
    }
    Write-Host "[dev_up] Done." -ForegroundColor Green
}
