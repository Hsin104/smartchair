# Start Web Dev with reliable Chrome connection
# - Kills leftover dartvm processes
# - Launches Chrome with a temporary user-data-dir and remote debugging enabled
# - Starts `flutter run` with an auto-selected port so hot reload works

param(
  [string]$ApiBaseUrl = "",
  [int]$DebuggingPort = 9222,
  [int]$FixedPort = 0
)

Write-Host "Cleaning leftover dartvm processes..."
Get-Process -Name dartvm -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }

# Find Chrome
$chromePaths = @(
  "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
  "$env:ProgramFiles(x86)\Google\Chrome\Application\chrome.exe"
)
$chrome = $chromePaths | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($null -ne $chrome) {
  $tmpProfile = Join-Path $env:TEMP "flutter_chrome_profile_$(Get-Random)"
  New-Item -ItemType Directory -Path $tmpProfile | Out-Null
  Write-Host "Launching Chrome with remote debugging on port $DebuggingPort..."
  Start-Process -FilePath $chrome -ArgumentList "--remote-debugging-port=$DebuggingPort","--user-data-dir=$tmpProfile","about:blank"
  Start-Sleep -Seconds 1
} else {
  Write-Warning "Chrome executable not found in default locations. Please start Chrome manually with --remote-debugging-port or ensure Chrome is installed."
}

# If a fixed port is requested, try to free it first so localStorage persists across runs
if ($FixedPort -ne 0) {
  Write-Host "Ensuring fixed web port $FixedPort is free..."
  $conn = Get-NetTCPConnection -LocalPort $FixedPort -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($conn) {
    $pid = $conn.OwningProcess
    try {
      Write-Host "Killing process $pid occupying port $FixedPort..."
      Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
    } catch {
      Write-Warning "Unable to kill process $pid. You may need to free port $FixedPort manually."
    }
    Start-Sleep -Milliseconds 300
  }
}

# Build flutter args
$webPortArg = if ($FixedPort -ne 0) { $FixedPort } else { 0 }
$flutterArgs = @("run","-d","chrome","--web-port",$webPortArg)
if ($ApiBaseUrl -ne "") {
  $flutterArgs += "--dart-define=API_BASE_URL=$ApiBaseUrl"
}

Write-Host "Starting flutter run..."
flutter @flutterArgs

# Cleanup: optional - keep profile for debugging
Write-Host "Done. If you want to remove the temporary Chrome profile, delete: $tmpProfile"