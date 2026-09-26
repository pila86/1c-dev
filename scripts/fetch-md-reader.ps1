# Build md-reader jar into the local 1c-dev tools cache (ADR-012).
# Requires: JDK 21+ (MDClasses 0.20.0). Uses tools\md-reader\gradlew.bat (Gradle 8.10.2).
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Src = Join-Path $Root "tools\md-reader"
$Pin = "mdclasses-0.20.0"

$CacheDir = Join-Path $env:LOCALAPPDATA "1c-dev\tools"
$PinnedJar = Join-Path $CacheDir "md-reader-$Pin.jar"
$StableJar = Join-Path $CacheDir "md-reader.jar"

function Get-JavaMajor([string]$JavaExe) {
    $versionOutput = & $JavaExe -version 2>&1 | Out-String
    if ($versionOutput -notmatch 'version "?(\d+)') {
        return $null
    }
    $major = [int]$Matches[1]
    if ($major -eq 1 -and $versionOutput -match 'version "1\.(\d+)') {
        $major = [int]$Matches[1]
    }
    return $major
}

function Get-JavaExe21 {
    $candidates = @()
    if ($env:JAVA_HOME) {
        $candidates += (Join-Path $env:JAVA_HOME "bin\java.exe")
    }
    $cmd = Get-Command java -ErrorAction SilentlyContinue
    if ($cmd) { $candidates += $cmd.Source }

    foreach ($java in $candidates) {
        if (-not (Test-Path $java)) { continue }
        $major = Get-JavaMajor $java
        if ($null -ne $major -and $major -ge 21) {
            return $java
        }
    }
    return $null
}

$Java = Get-JavaExe21
if (-not $Java) {
    Write-Error "Java 21+ required for md-reader / MDClasses (set JAVA_HOME or install JDK 21)"
}

$env:JAVA_HOME = (Resolve-Path (Join-Path (Split-Path $Java) "..")).Path

New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null
if (Test-Path $PinnedJar) {
    Copy-Item -Force $PinnedJar $StableJar
    Write-Host "md-reader already built: $StableJar"
    exit 0
}

$Gradlew = Join-Path $Src "gradlew.bat"
if (-not (Test-Path $Gradlew)) {
    Write-Error "gradlew.bat not found in $Src"
}

Write-Host "Building md-reader ($Pin) with Java $($env:JAVA_HOME)..."
Push-Location $Src
try {
    & .\gradlew.bat fatJar --no-daemon -q
    if ($LASTEXITCODE -ne 0) { throw "gradlew failed with exit $LASTEXITCODE" }
} finally {
    Pop-Location
}

$Built = Join-Path $Src "build\libs\md-reader.jar"
if (-not (Test-Path $Built)) { throw "built jar not found: $Built" }

Copy-Item -Force $Built $PinnedJar
Copy-Item -Force $PinnedJar $StableJar
Write-Host "Installed: $StableJar"
