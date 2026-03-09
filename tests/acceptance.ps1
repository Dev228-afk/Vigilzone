# ──────────────────────────────────────────────────────────────
# VigilZone Acceptance Tests (PowerShell)
#
# Prerequisites:
#   - Django backend on $env:BACKEND (default: http://localhost:8000)
#   - AI module on $env:AI_BASE (default: http://localhost:8080)
#   - User "dev" / "VigilZone2024!"
#
# Usage:
#   .\tests\acceptance.ps1
# ──────────────────────────────────────────────────────────────
$ErrorActionPreference = "Continue"

$BACKEND  = if ($env:BACKEND)  { $env:BACKEND }  else { "http://localhost:8000" }
$AI_BASE  = if ($env:AI_BASE)  { $env:AI_BASE }  else { "http://localhost:8080" }
$USERNAME = if ($env:TEST_USER){ $env:TEST_USER } else { "dev" }
$PASSWORD = if ($env:TEST_PASS){ $env:TEST_PASS } else { "VigilZone2024!" }
$TENANT   = if ($env:TENANT_ID){ $env:TENANT_ID } else { "2" }

$pass = 0; $fail = 0

function Test-Endpoint {
    param([string]$Name, [int]$Got, [int]$Expected)
    if ($Got -eq $Expected) {
        Write-Host "  + $Name (HTTP $Got)" -ForegroundColor Green
        $script:pass++
    } else {
        Write-Host "  x $Name -- expected $Expected, got $Got" -ForegroundColor Red
        $script:fail++
    }
}

Write-Host "`n=== VigilZone Acceptance Tests ===" -ForegroundColor Cyan
Write-Host "  Backend : $BACKEND"
Write-Host "  AI      : $AI_BASE`n"

# ── 1. Auth ───────────────────────────────────────────────────
Write-Host "# Auth" -ForegroundColor Yellow
try {
    $body = @{ username = $USERNAME; password = $PASSWORD } | ConvertTo-Json
    $resp = Invoke-RestMethod -Uri "$BACKEND/api/auth/token/" -Method POST `
        -ContentType "application/json" -Body $body -ErrorAction Stop
    $TOKEN = $resp.access
    Test-Endpoint "POST /api/auth/token/" 200 200
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    Test-Endpoint "POST /api/auth/token/" $code 200
    Write-Host "  Cannot proceed without token." -ForegroundColor Red
    exit 1
}

$headers = @{
    "Authorization" = "Bearer $TOKEN"
    "X-Tenant-ID"   = $TENANT
}

# ── 2. Core Django ────────────────────────────────────────────
Write-Host "`n# Core API (Django)" -ForegroundColor Yellow
$endpoints = @(
    "/api/cameras/",
    "/api/incidents/",
    "/api/detections/",
    "/api/audit/",
    "/api/dashboard/summary/",
    "/api/incidents/stats/",
    "/api/profile/me/",
    "/api/auth/context/"
)
foreach ($ep in $endpoints) {
    try {
        $null = Invoke-WebRequest -Uri "$BACKEND$ep" -Headers $headers -UseBasicParsing -ErrorAction Stop
        Test-Endpoint "GET $ep" 200 200
    } catch {
        $code = if ($_.Exception.Response) { $_.Exception.Response.StatusCode.value__ } else { 0 }
        Test-Endpoint "GET $ep" $code 200
    }
}

# ── 3. AI Proxy ───────────────────────────────────────────────
Write-Host "`n# AI Proxy (Django -> AI)" -ForegroundColor Yellow
$aiEndpoints = @(
    "/api/ai/cameras/",
    "/api/ai/alerts/",
    "/api/ai/system/status/",
    "/api/ai/entities/"
)
foreach ($ep in $aiEndpoints) {
    try {
        $null = Invoke-WebRequest -Uri "$BACKEND$ep" -Headers $headers -UseBasicParsing -ErrorAction Stop
        Test-Endpoint "GET $ep" 200 200
    } catch {
        $code = if ($_.Exception.Response) { $_.Exception.Response.StatusCode.value__ } else { 0 }
        Test-Endpoint "GET $ep" $code 200
    }
}

# Frame snapshot
try {
    $null = Invoke-WebRequest -Uri "$BACKEND/api/ai/frame/cam_live/" -Headers $headers -UseBasicParsing -ErrorAction Stop
    Test-Endpoint "GET /api/ai/frame/cam_live/" 200 200
} catch {
    $code = if ($_.Exception.Response) { $_.Exception.Response.StatusCode.value__ } else { 0 }
    Write-Host "  ! GET /api/ai/frame/cam_live/ -- HTTP $code (camera may be offline)" -ForegroundColor DarkYellow
}

# ── 4. Webhook Persistence ───────────────────────────────────
Write-Host "`n# Webhook Persistence" -ForegroundColor Yellow
$ts = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
$whBody = @{
    event = "alert.created"
    data  = @{
        id         = "test-ps-001"
        camera_id  = "cam_live"
        type       = "fire"
        severity   = "high"
        timestamp  = $ts
        message    = "PowerShell acceptance test: fire detected"
        confidence = 0.91
        evidence   = @{}
    }
} | ConvertTo-Json -Depth 5
try {
    $whResp = Invoke-WebRequest -Uri "$BACKEND/api/ai/webhook/receive/" -Method POST `
        -ContentType "application/json" -Body $whBody -UseBasicParsing -ErrorAction Stop
    $whCode = $whResp.StatusCode
    if ($whCode -eq 200 -or $whCode -eq 201) {
        Test-Endpoint "POST /api/ai/webhook/receive/" $whCode $whCode
    } else {
        Test-Endpoint "POST /api/ai/webhook/receive/" $whCode 201
    }
} catch {
    $code = if ($_.Exception.Response) { $_.Exception.Response.StatusCode.value__ } else { 0 }
    Test-Endpoint "POST /api/ai/webhook/receive/" $code 201
}

# Verify persisted
try {
    $null = Invoke-WebRequest -Uri "$BACKEND/api/incidents/?type=FIRE" -Headers $headers -UseBasicParsing -ErrorAction Stop
    Test-Endpoint "GET /api/incidents/?type=FIRE (verify)" 200 200
} catch {
    $code = if ($_.Exception.Response) { $_.Exception.Response.StatusCode.value__ } else { 0 }
    Test-Endpoint "GET /api/incidents/?type=FIRE (verify)" $code 200
}

# ── 5. AI Direct ─────────────────────────────────────────────
Write-Host "`n# AI Module Direct" -ForegroundColor Yellow
try {
    $null = Invoke-WebRequest -Uri "$AI_BASE/api/v1/system/status" -UseBasicParsing -ErrorAction Stop
    Test-Endpoint "GET /api/v1/system/status (AI)" 200 200
} catch {
    $code = if ($_.Exception.Response) { $_.Exception.Response.StatusCode.value__ } else { 0 }
    Test-Endpoint "GET /api/v1/system/status (AI)" $code 200
}
try {
    $null = Invoke-WebRequest -Uri "$AI_BASE/webhooks" -UseBasicParsing -ErrorAction Stop
    Test-Endpoint "GET /webhooks (AI)" 200 200
} catch {
    $code = if ($_.Exception.Response) { $_.Exception.Response.StatusCode.value__ } else { 0 }
    Test-Endpoint "GET /webhooks (AI)" $code 200
}

# ── Summary ───────────────────────────────────────────────────
Write-Host "`n==================================================="
Write-Host "  Results: $pass passed, $fail failed" -ForegroundColor $(if ($fail -eq 0) { "Green" } else { "Red" })
Write-Host "==================================================="

exit $fail
