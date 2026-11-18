# Baut SpielschnittSetup.exe
#   1. PyInstaller: Spielschnitt.pyw -> build\dist\Spielschnitt\Spielschnitt.exe (ohne Konsole)
#   2. ffmpeg.exe + ffprobe.exe dazulegen (aus dem PATH oder -FFmpegDir)
#   3. Inno Setup: build\out\SpielschnittSetup.exe
#
# Voraussetzungen:  python -m pip install pyinstaller
#                   winget install JRSoftware.InnoSetup
# Aufruf:           powershell -ExecutionPolicy Bypass -File build\build.ps1 -Version 1.0.0

param(
    [string]$Version = "1.0.0",
    [string]$FFmpegDir = ""
)
$ErrorActionPreference = "Stop"
$Build = $PSScriptRoot
$Root = Split-Path $Build
$Dist = Join-Path $Build "dist"
$App = Join-Path $Dist "Spielschnitt"

Write-Host "== 1/3 PyInstaller" -ForegroundColor Cyan
if (Test-Path $Dist) { Remove-Item -Recurse -Force $Dist }
python -m PyInstaller --noconfirm --clean --windowed `
    --name Spielschnitt `
    --icon (Join-Path $Root "app\spielschnitt.ico") `
    --add-data "$(Join-Path $Root 'app\ui');app\ui" `
    --hidden-import app.server `
    --paths $Root `
    --distpath $Dist `
    --workpath (Join-Path $Build "work") `
    --specpath $Build `
    (Join-Path $Root "Spielschnitt.pyw")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller ist fehlgeschlagen." }

Write-Host "== 2/3 ffmpeg dazulegen" -ForegroundColor Cyan
if (-not $FFmpegDir) { $FFmpegDir = Split-Path (Get-Command ffmpeg -ErrorAction Stop).Source }
$ff = New-Item -ItemType Directory -Force (Join-Path $App "ffmpeg")
Copy-Item (Join-Path $FFmpegDir "ffmpeg.exe"), (Join-Path $FFmpegDir "ffprobe.exe") $ff
$lic = Join-Path (Split-Path $FFmpegDir) "LICENSE"
if (Test-Path $lic) { Copy-Item $lic (Join-Path $ff "LICENSE.txt") }
Copy-Item (Join-Path $Build "DRITTANBIETER.txt") $App

Write-Host "== 3/3 Inno Setup" -ForegroundColor Cyan
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 nicht gefunden (winget install JRSoftware.InnoSetup)." }
& $iscc "/DAppVersion=$Version" "/DDistDir=$App" "/DOutDir=$(Join-Path $Build 'out')" (Join-Path $Build "SpielschnittSetup.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup ist fehlgeschlagen." }

$setup = Join-Path $Build "out\SpielschnittSetup.exe"
Write-Host ("Fertig: {0} ({1:N0} MB)" -f $setup, ((Get-Item $setup).Length / 1MB)) -ForegroundColor Green
