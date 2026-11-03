param(
  [switch]$Tunnel,
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$appRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$connectionFlag = if ($Tunnel) { "--tunnel" } else { "--lan" }
$expoArguments = @("--no-install", "expo", "start", "--go", $connectionFlag, "--clear", "--port", "8081")
$displayCommand = "npx " + ($expoArguments -join " ")

Write-Host "NC Main Chat Remote - Expo Go"
Write-Host "Project: $appRoot"
Write-Host "Command: $displayCommand"
Write-Host "Scan the QR code with Expo Go on the Pixel."
Write-Host "Use npm run go:tunnel if LAN discovery is blocked."

if ($DryRun) {
  exit 0
}

Set-Location -LiteralPath $appRoot
if (-not (Test-Path -LiteralPath (Join-Path $appRoot "node_modules\.bin\expo.cmd"))) {
  Write-Host "Expo dependencies are missing. Running npm ci once..."
  & npm ci
  if ($LASTEXITCODE -ne 0) {
    throw "npm ci failed with exit code $LASTEXITCODE"
  }
}
& npx @expoArguments
exit $LASTEXITCODE
