# Build pinned xml-gen jar into the local 1c-dev tools cache (ADR-007).
# Requires: JDK 17+, git, PowerShell 5.1+ / 7+
$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/SteelMorgan/1c-agent-based-dev-framework.git"
$Commit = "19f67bfed6d15f051f9568678bab1701b7735f95"
$Short = $Commit.Substring(0, 12)

$CacheDir = Join-Path $env:LOCALAPPDATA "1c-dev\tools"
$PinnedJar = Join-Path $CacheDir "xml-gen-$Short.jar"
$StableJar = Join-Path $CacheDir "xml-gen.jar"

function Get-JavaExe {
    if ($env:JAVA_HOME) {
        $candidate = Join-Path $env:JAVA_HOME "bin\java.exe"
        if (Test-Path $candidate) { return $candidate }
    }
    $cmd = Get-Command java -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

$Java = Get-JavaExe
if (-not $Java) {
    Write-Error "Java 17+ required (set JAVA_HOME or add java to PATH)"
}

$versionOutput = & $Java -version 2>&1 | Out-String
if ($versionOutput -notmatch 'version "?(\d+)') {
    Write-Error "cannot parse java -version"
}
$major = [int]$Matches[1]
if ($major -eq 1 -and $versionOutput -match 'version "1\.(\d+)') {
    $major = [int]$Matches[1]
}
if ($major -lt 17) {
    Write-Error "Java 17+ required (found major $major)"
}

New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null
if (Test-Path $PinnedJar) {
    Copy-Item -Force $PinnedJar $StableJar
    Write-Host "xml-gen already built: $StableJar"
    exit 0
}

$Work = Join-Path ([System.IO.Path]::GetTempPath()) ("1c-dev-xmlgen-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $Work | Out-Null
try {
    Write-Host "Cloning xml-gen @ $Short..."
    $Src = Join-Path $Work "src"
    git clone --filter=blob:none --sparse $RepoUrl $Src
    git -C $Src sparse-checkout set tools/xml-gen
    git -C $Src checkout $Commit

    Write-Host "Building xml-gen..."
    Push-Location (Join-Path $Src "tools\xml-gen")
    try {
        & .\gradlew.bat build -x test --no-daemon -q
        if ($LASTEXITCODE -ne 0) { throw "gradlew failed with exit $LASTEXITCODE" }
    } finally {
        Pop-Location
    }

    $Built = Get-ChildItem (Join-Path $Src "tools\xml-gen\build\libs\xml-gen-*.jar") |
        Select-Object -First 1
    if (-not $Built) { throw "built jar not found" }

    Copy-Item -Force $Built.FullName $PinnedJar
    Copy-Item -Force $PinnedJar $StableJar
    Write-Host "Installed: $StableJar"
} finally {
    Remove-Item -Recurse -Force $Work -ErrorAction SilentlyContinue
}
