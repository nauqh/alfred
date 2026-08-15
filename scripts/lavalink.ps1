# Fetch and run a Lavalink node on this machine, for developing without Docker.
#
# The Docker path (`docker compose up -d`) is what deployment uses and is unaffected
# by this script - it exists so the node can run on a laptop with no daemon.
#
#   .\scripts\lavalink.ps1          # run the node (downloads the jar on first use)
#   .\scripts\lavalink.ps1 -Update  # re-download the jar, then run

[CmdletBinding()]
param(
    # Keep in step with the image tag in docker-compose.yml, so the node you develop
    # against is the node you deploy.
    [string]$Version = "4.2.2",
    [switch]$Update
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$dir = Join-Path $root "lavalink"
$jar = Join-Path $dir "Lavalink.jar"
$config = Join-Path $dir "application.yml"

if (-not (Test-Path $config)) {
    throw "$config does not exist. Copy lavalink/application.yml.example to it and fill in the credentials."
}

if ($Update -or -not (Test-Path $jar)) {
    $url = "https://github.com/lavalink-devs/Lavalink/releases/download/$Version/Lavalink.jar"
    Write-Host "Downloading Lavalink $Version (~96 MB)..." -ForegroundColor Cyan
    Invoke-WebRequest -Uri $url -OutFile $jar -TimeoutSec 900
}

# Lavalink 4 needs Java 17+. winget puts the Microsoft build here without touching
# this session's PATH, so look there before giving up on `java`.
$java = (Get-Command java -ErrorAction SilentlyContinue).Source
if (-not $java) {
    $jdk = Get-ChildItem "C:\Program Files\Microsoft\jdk-*" -Directory -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending | Select-Object -First 1
    if ($jdk) { $java = Join-Path $jdk.FullName "bin\java.exe" }
}
if (-not $java) {
    throw "No Java found. Install one with: winget install --id Microsoft.OpenJDK.21 -e"
}

# Run from lavalink/, which is where the node resolves application.yml, plugins/ and logs/.
Push-Location $dir
try {
    Write-Host "Starting Lavalink $Version on http://127.0.0.1:2333 (ctrl-c to stop)" -ForegroundColor Green
    & $java -jar $jar
}
finally {
    Pop-Location
}
