# Build pinned xml-gen jar into the local 1c-dev tools cache (ADR-007 / ADR-018).
# Pin covers Meta DSL 23 + subsystem compile/edit.
# Requires: JDK 25+, git, PowerShell 5.1+ / 7+ (единый JDK с md-sparrow).
$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/SteelMorgan/1c-agent-based-dev-framework.git"
$Commit = "19f67bfed6d15f051f9568678bab1701b7735f95"
$Short = $Commit.Substring(0, 12)
$GradleVer = "9.1.0"

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
    Write-Error "Java 25+ required (set JAVA_HOME or add java to PATH)"
}

$versionOutput = & $Java -version 2>&1 | Out-String
if ($versionOutput -notmatch 'version "?(\d+)') {
    Write-Error "cannot parse java -version"
}
$major = [int]$Matches[1]
if ($major -eq 1 -and $versionOutput -match 'version "1\.(\d+)') {
    $major = [int]$Matches[1]
}
if ($major -lt 25) {
    Write-Error "Java 25+ required (found major $major)"
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

    $Proj = Join-Path $Src "tools\xml-gen"
    $Props = Join-Path $Proj "gradle\wrapper\gradle-wrapper.properties"
    if (Test-Path $Props) {
        $propsText = Get-Content -Raw $Props
        $propsText = [regex]::Replace(
            $propsText,
            'gradle-[0-9.]+-bin\.zip',
            "gradle-$GradleVer-bin.zip"
        )
        Set-Content -Path $Props -Value $propsText -NoNewline
    }
    $BuildKts = Join-Path $Proj "build.gradle.kts"
    if (Test-Path $BuildKts) {
        $buildText = Get-Content -Raw $BuildKts
        $buildText = [regex]::Replace(
            $buildText,
            'id\(\s*"(?:com\.github\.johnrengelman\.shadow|com\.gradleup\.shadow)"\s*\)\s+version\s+"[^"]+"',
            'id("com.gradleup.shadow") version "9.0.2"'
        )
        $buildText = [regex]::Replace(
            $buildText,
            'JavaLanguageVersion\.of\(\s*\d+\s*\)',
            'JavaLanguageVersion.of(25)'
        )
        Set-Content -Path $BuildKts -Value $buildText -NoNewline
    }

    Write-Host "Building xml-gen (Gradle $GradleVer, JDK $major)..."
    Push-Location $Proj
    try {
        & .\gradlew.bat build -x test --no-daemon -q
        if ($LASTEXITCODE -ne 0) { throw "gradlew failed with exit $LASTEXITCODE" }
    } finally {
        Pop-Location
    }

    $Built = Get-ChildItem (Join-Path $Proj "build\libs\xml-gen-*.jar") |
        Select-Object -First 1
    if (-not $Built) { throw "built jar not found" }

    Copy-Item -Force $Built.FullName $PinnedJar
    Copy-Item -Force $PinnedJar $StableJar
    Write-Host "Installed: $StableJar"
} finally {
    Remove-Item -Recurse -Force $Work -ErrorAction SilentlyContinue
}
