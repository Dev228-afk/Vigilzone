# ── Create VigilZone Context Zip ────────────────────────────
# Packages the repository into a zip while excluding large model
# weights, virtual envs, node_modules, caches, and logs.
# Usage: run from any PowerShell prompt; adjust $root/ $zipOut if needed.

$ErrorActionPreference = "Stop"
$root = "c:\Users\devan\OneDrive\Desktop\yolov12-cls\vigilzone-monolith"
$zipOut = "c:\Users\devan\OneDrive\Desktop\yolov12-cls\vigilzone-context.zip"
$tempDir = "$env:TEMP\vigilzone-context"

# Clean up
if (Test-Path $tempDir) { Remove-Item $tempDir -Recurse -Force }
if (Test-Path $zipOut)  { Remove-Item $zipOut -Force }
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

# Exclude patterns (directories and globs)
$excludeDirs = @('node_modules', '\\.venv', '\\venv', '__pycache__')
$excludeFilePatterns = @('*.log')

# Common model weight extensions to exclude
$excludeExt = @('.pt','.onnx','.pth','.bin','.mat','.tar','.tgz','.zip','.ckpt')

# Also exclude very large files by size (MB)
$maxSizeMB = 50

Write-Host "Scanning files under $root (this may take a while)..." -ForegroundColor Cyan

$files = Get-ChildItem -Path $root -Recurse -File -Force -ErrorAction SilentlyContinue |
    Where-Object {
        $full = $_.FullName
        # Skip the output zip itself
        if ($full -ieq $zipOut) { return $false }

        # Exclude if any excluded dir is in the path
        foreach ($token in $excludeDirs) {
            if ($full -match [regex]::Escape($token)) { return $false }
        }

        # Exclude log files
        foreach ($pat in $excludeFilePatterns) {
            if ($full -like $pat) { return $false }
        }

        # Exclude by extension
        if ($excludeExt -contains $_.Extension.ToLower()) { return $false }

        # Exclude by size
        if ($_.Length -gt ($maxSizeMB * 1MB)) { return $false }

        return $true
    }

$copied = 0
$skipped = 0
foreach ($f in $files) {
    try {
        $relPath = $f.FullName.Substring($root.Length).TrimStart('\','/')
        $dest = Join-Path $tempDir $relPath
        $destDir = Split-Path $dest -Parent
        if (-not (Test-Path $destDir)) { New-Item -ItemType Directory -Path $destDir -Force | Out-Null }
        Copy-Item -LiteralPath $f.FullName -Destination $dest -Force
        $copied++
    } catch {
        Write-Host "SKIP (error copying): $($f.FullName) — $($_.Exception.Message)" -ForegroundColor Yellow
        $skipped++
    }
}

# Optionally include top-level helper docs if present (legacy)
$legacyInst = "c:\Users\devan\OneDrive\Desktop\yolov12-cls\ai_module\instructions.md"
if (Test-Path $legacyInst) {
    Copy-Item $legacyInst (Join-Path $tempDir 'instructions.md') -Force
    $copied++
}

Write-Host "`nFiles copied: $copied, skipped: $skipped" -ForegroundColor Cyan

# Create zip
Compress-Archive -Path "$tempDir\*" -DestinationPath $zipOut -Force
$size = (Get-Item $zipOut).Length
$sizeKB = [math]::Round($size / 1024, 1)

Write-Host "`n=== Context zip created ===" -ForegroundColor Green
Write-Host "  Path: $zipOut"
Write-Host "  Size: $sizeKB KB ($copied files)"

# Clean up temp
Remove-Item $tempDir -Recurse -Force
