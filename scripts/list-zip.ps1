Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = 'c:\Users\devan\OneDrive\Desktop\yolov12-cls\vigilzone-context.zip'
if (Test-Path $zip) {
  $e = [System.IO.Compression.ZipFile]::OpenRead($zip).Entries
  Write-Output "ZIP_EXISTS;$($e.Count)"
  $e | Select-Object FullName,Length | Select-Object -First 200 | ForEach-Object { "{0}|{1}" -f $_.FullName, $_.Length }
} else {
  Write-Output "ZIP_NOT_FOUND"
}
