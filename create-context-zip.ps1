# ── Create VigilZone Context Zip ────────────────────────────
# Packages all key source files into a single zip for sharing
# context with AI assistants, code reviewers, etc.
# ────────────────────────────────────────────────────────────

$ErrorActionPreference = "SilentlyContinue"
$root = "c:\Users\devan\OneDrive\Desktop\yolov12-cls\vigilzone-monolith"
$zipOut = "c:\Users\devan\OneDrive\Desktop\yolov12-cls\vigilzone-context.zip"
$tempDir = "$env:TEMP\vigilzone-context"

# Clean up
if (Test-Path $tempDir) { Remove-Item $tempDir -Recurse -Force }
if (Test-Path $zipOut)  { Remove-Item $zipOut -Force }
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

# Collect file list (relative to monorepo root)
$relPaths = @(
    # Docker & config
    "docker-compose.yml",
    ".env.example",
    "README.md",

    # Backend — Django
    "services/backend/Dockerfile",
    "services/backend/requirements.txt",
    "services/backend/manage.py",
    "services/backend/server/settings.py",
    "services/backend/server/urls.py",
    "services/backend/server/wsgi.py",
    "services/backend/api/models.py",
    "services/backend/api/serializers.py",
    "services/backend/api/views.py",
    "services/backend/api/urls.py",
    "services/backend/api/admin.py",
    "services/backend/api/apps.py",
    "services/backend/ai_integration/views.py",
    "services/backend/ai_integration/urls.py",
    "services/backend/ai_integration/proxy.py",
    "services/backend/ai_integration/apps.py",
    "services/backend/ai_integration/management/commands/register_ai_webhook.py",
    "services/backend/ai_integration/management/commands/close_stale_incidents.py",

    # AI service
    "services/ai/Dockerfile",
    "services/ai/requirements.txt",
    "services/ai/run.py",
    "services/ai/configs/cameras.yaml",
    "services/ai/configs/cameras.docker.yaml",
    "services/ai/configs/models.yaml",
    "services/ai/configs/zones.yaml",
    "services/ai/configs/policy.yaml",
    "services/ai/src/api/server.py",
    "services/ai/src/common/config.py",
    "services/ai/src/app.py",

    # Webcam publisher
    "services/webcam_publisher/Dockerfile",
    "services/webcam_publisher/entrypoint.sh",

    # UI — React/Vite
    "web/ui/vite.config.ts",
    "web/ui/package.json",
    "web/ui/tsconfig.json",
    "web/ui/client/src/main.tsx",
    "web/ui/client/src/App.tsx",
    "web/ui/client/src/index.css",
    "web/ui/client/src/lib/api.ts",
    "web/ui/client/src/lib/memberships.ts",
    "web/ui/client/src/lib/invitations.ts",
    "web/ui/client/src/auth/AuthProvider.tsx",
    "web/ui/client/src/pages/Dashboard.tsx",
    "web/ui/client/src/pages/LiveAI.tsx",
    "web/ui/client/src/pages/Cameras.tsx",
    "web/ui/client/src/pages/Incidents.tsx",
    "web/ui/client/src/pages/IncidentDetails.tsx",
    "web/ui/client/src/pages/Reports.tsx",
    "web/ui/client/src/pages/Settings.tsx",
    "web/ui/client/src/pages/Community.tsx",
    "web/ui/client/src/pages/Entities.tsx",
    "web/ui/client/src/pages/Login.tsx",
    "web/ui/client/src/pages/Register.tsx",
    "web/ui/client/src/pages/ForgotPassword.tsx",
    "web/ui/client/src/pages/SelectCommunity.tsx",
    "web/ui/client/src/components/NavBar.tsx",

    # Nginx
    "deploy/nginx/nginx.conf",

    # Tests
    "tests/acceptance.sh",
    "tests/acceptance.ps1"
)

$copied = 0
$missing = 0
foreach ($rel in $relPaths) {
    $src = Join-Path $root ($rel -replace '/', '\')
    if (Test-Path $src) {
        $dest = Join-Path $tempDir $rel
        $destDir = Split-Path $dest -Parent
        if (-not (Test-Path $destDir)) {
            New-Item -ItemType Directory -Path $destDir -Force | Out-Null
        }
        Copy-Item $src $dest -Force
        $copied++
    } else {
        $missing++
        Write-Host "  SKIP (not found): $rel" -ForegroundColor DarkYellow
    }
}

# Also include instructions.md from ai_module if it exists
$inst = "c:\Users\devan\OneDrive\Desktop\yolov12-cls\ai_module\instructions.md"
if (Test-Path $inst) {
    $destInst = Join-Path $tempDir "instructions.md"
    Copy-Item $inst $destInst -Force
    $copied++
}

Write-Host "`nFiles copied: $copied, skipped: $missing" -ForegroundColor Cyan

# Create zip
Compress-Archive -Path "$tempDir\*" -DestinationPath $zipOut -Force
$size = (Get-Item $zipOut).Length
$sizeKB = [math]::Round($size / 1024, 1)

Write-Host "`n=== Context zip created ===" -ForegroundColor Green
Write-Host "  Path: $zipOut"
Write-Host "  Size: $sizeKB KB ($copied files)"

# Clean up temp
Remove-Item $tempDir -Recurse -Force
