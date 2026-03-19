# Create VigilZone context zip
# Goal: keep rich code/doc context for architect LLM while guaranteeing
# output zip stays under the target size.

$ErrorActionPreference = "Stop"
$root = "c:\Users\devan\OneDrive\Desktop\yolov12-cls\vigilzone-monolith"
$zipOut = "c:\Users\devan\OneDrive\Desktop\yolov12-cls\vigilzone-context.zip"
$tempDir = "$env:TEMP\vigilzone-context"
$targetZipMaxMB = 65
$targetZipMaxBytes = $targetZipMaxMB * 1MB
# Keep staging budget conservative because text compresses, binaries do not.
$stagingSoftBudgetBytes = 190MB

# Clean up
if (Test-Path $tempDir) { Remove-Item $tempDir -Recurse -Force }
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

# Directory and file exclusions that are almost never useful for LLM context.
$excludeDirTokens = @(
    "\node_modules\", "\.venv\", "\venv\", "\__pycache__\", "\.git\", "\dist\", "\build\"
)
$excludeFilePatterns = @('*.log', '*.tmp', '*.bak', '*.cache')

# Binary/model/archive extensions excluded by default.
$excludeExt = @(
    '.pt','.onnx','.pth','.bin','.mat','.tar','.tgz','.zip','.ckpt','.db','.sqlite','.h5','.pb','.weights',
    '.jpg','.jpeg','.png','.gif','.webp','.bmp','.ico','.mp4','.avi','.mov','.mkv','.wav','.mp3','.flac',
    '.pdf','.exe','.dll','.so','.dylib'
)

# Text/code extensions always considered high-value context.
$preferredTextExt = @(
    '.py','.pyi','.js','.jsx','.ts','.tsx','.json','.yaml','.yml','.toml','.ini','.cfg','.conf','.md','.txt',
    '.sh','.ps1','.bat','.cmd','.dockerfile','.env','.gitignore','.gitattributes','.sql','.csv','.xml','.html',
    '.css','.scss','.sass','.less','.java','.go','.rs','.c','.cc','.cpp','.h','.hpp','.cs','.rb','.php','.swift'
)

# Optional files can be trimmed only if the zip still exceeds max size.
$optionalTrimPathTokens = @(
    "\assets\", "\attached_assets\", "\gradio_cached_examples\", "\local_db\evidence\"
)

function Test-IsLikelyTextFile {
    param([System.IO.FileInfo]$File)

    $ext = $File.Extension.ToLowerInvariant()
    if ($preferredTextExt -contains $ext) { return $true }
    if ($excludeExt -contains $ext) { return $false }

    # Fast content heuristic for unknown extensions.
    $stream = $null
    try {
        $stream = [System.IO.File]::OpenRead($File.FullName)
        $len = [Math]::Min(4096, [int]$stream.Length)
        if ($len -le 0) { return $true }

        $buffer = New-Object byte[] $len
        [void]$stream.Read($buffer, 0, $len)

        $nullBytes = 0
        foreach ($b in $buffer) {
            if ($b -eq 0) { $nullBytes++ }
        }
        return ($nullBytes -eq 0)
    }
    catch {
        return $false
    }
    finally {
        if ($stream) { $stream.Dispose() }
    }
}

function New-ContextZip {
    if (Test-Path $zipOut) { Remove-Item $zipOut -Force }
    Compress-Archive -Path "$tempDir\*" -DestinationPath $zipOut -Force
    return (Get-Item $zipOut).Length
}

function Test-FileLocked {
    param([string]$Path)

    if (-not (Test-Path $Path)) { return $false }
    $stream = $null
    try {
        $stream = [System.IO.File]::Open($Path, 'Open', 'ReadWrite', 'None')
        return $false
    }
    catch {
        return $true
    }
    finally {
        if ($stream) { $stream.Dispose() }
    }
}

# Pick an output file that is writable.
if (Test-Path $zipOut) {
    if (Test-FileLocked -Path $zipOut) {
        $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $zipDir = Split-Path $zipOut -Parent
        $zipName = [System.IO.Path]::GetFileNameWithoutExtension($zipOut)
        $zipOut = Join-Path $zipDir ("{0}-{1}.zip" -f $zipName, $stamp)
        Write-Host "Primary zip path is locked; using fallback output: $zipOut" -ForegroundColor Yellow
    }
}

Write-Host "Scanning files under $root (this may take a while)..." -ForegroundColor Cyan

$allFiles = Get-ChildItem -Path $root -Recurse -File -Force -ErrorAction SilentlyContinue |
    Where-Object {
        $full = $_.FullName
        $lower = $full.ToLowerInvariant()

        # Skip the output zip itself
        if ($full -ieq $zipOut) { return $false }

        # Exclude if any excluded dir is in the path
        foreach ($token in $excludeDirTokens) {
            if ($lower.Contains($token.ToLowerInvariant())) { return $false }
        }

        # Exclude log files
        foreach ($pat in $excludeFilePatterns) {
            if ($_.Name -like $pat) { return $false }
        }

        # Exclude by extension
        if ($excludeExt -contains $_.Extension.ToLowerInvariant()) { return $false }

        return $true
    }

$selected = @()
$optionalCandidates = @()
$skippedBinary = 0

foreach ($f in $allFiles) {
    if (-not (Test-IsLikelyTextFile -File $f)) {
        $skippedBinary++
        continue
    }

    $relPath = $f.FullName.Substring($root.Length).TrimStart('\','/')
    $relLower = $relPath.ToLowerInvariant()

    $isOptional = $false
    foreach ($token in $optionalTrimPathTokens) {
        if ($relLower.Contains($token.TrimStart('\\').ToLowerInvariant())) {
            $isOptional = $true
            break
        }
    }

    $entry = [PSCustomObject]@{
        File = $f
        RelPath = $relPath
        IsOptional = $isOptional
    }
    $selected += $entry
    if ($isOptional) { $optionalCandidates += $entry }
}

$selectedTotalBytes = (($selected | ForEach-Object { $_.File.Length }) | Measure-Object -Sum).Sum

# If text corpus is still too large, pre-trim optional largest files first.
if ($selectedTotalBytes -gt $stagingSoftBudgetBytes -and $optionalCandidates.Count -gt 0) {
    $toTrim = $selectedTotalBytes - $stagingSoftBudgetBytes
    $trimmedPreBytes = 0

    foreach ($entry in ($optionalCandidates | Sort-Object { $_.File.Length } -Descending)) {
        if ($trimmedPreBytes -ge $toTrim) { break }
        $selected = $selected | Where-Object { $_.RelPath -ne $entry.RelPath }
        $trimmedPreBytes += $entry.File.Length
    }

    Write-Host "Pre-trimmed optional text/media context: $([Math]::Round($trimmedPreBytes / 1MB, 2)) MB" -ForegroundColor Yellow
}

$copied = 0
$skipped = 0
foreach ($entry in $selected) {
    $f = $entry.File
    try {
        $dest = Join-Path $tempDir $entry.RelPath
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

Write-Host "`nFiles copied: $copied, skipped: $skipped, skipped-binary: $skippedBinary" -ForegroundColor Cyan

# Create zip and enforce size budget by trimming optional files only.
$size = New-ContextZip
$trimmedPostCount = 0
$trimmedPostBytes = 0

if ($size -gt $targetZipMaxBytes) {
    Write-Host "Zip is over target ($([Math]::Round($size / 1MB, 2)) MB > $targetZipMaxMB MB). Trimming optional files..." -ForegroundColor Yellow

    # Build optional list that is actually in tempDir.
    $optionalInTemp = Get-ChildItem -Path $tempDir -Recurse -File -Force |
        Where-Object {
            $p = $_.FullName.Substring($tempDir.Length).TrimStart('\\','/').ToLowerInvariant()
            foreach ($token in $optionalTrimPathTokens) {
                $tok = $token.TrimStart('\\').ToLowerInvariant()
                if ($p.Contains($tok)) { return $true }
            }
            return $false
        } |
        Sort-Object Length -Descending

    foreach ($f in $optionalInTemp) {
        if ($size -le $targetZipMaxBytes) { break }
        $len = $f.Length
        Remove-Item -LiteralPath $f.FullName -Force
        $trimmedPostCount++
        $trimmedPostBytes += $len
        $size = New-ContextZip
    }
}

if ($size -gt $targetZipMaxBytes) {
    throw "Could not reduce context zip below $targetZipMaxMB MB without dropping high-priority text/code files. Consider increasing target or adding explicit low-priority paths."
}

$sizeKB = [math]::Round($size / 1024, 1)
$sizeMB = [math]::Round($size / 1MB, 2)

Write-Host "`n=== Context zip created ===" -ForegroundColor Green
Write-Host "  Path: $zipOut"
Write-Host "  Size: $sizeKB KB ($sizeMB MB, $copied files)"
Write-Host "  Target: <= $targetZipMaxMB MB"
if ($trimmedPostCount -gt 0) {
    Write-Host "  Optional files trimmed after zip pass: $trimmedPostCount ($([Math]::Round($trimmedPostBytes / 1MB, 2)) MB source)" -ForegroundColor Yellow
}

# Clean up temp
Remove-Item $tempDir -Recurse -Force
