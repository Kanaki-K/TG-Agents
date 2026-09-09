# threads_insights.ps1 - ezhednevnyy snimok stranicy Insights Vashim zhe Chrome.
#
# ZACHEM. Podpisok i zahodov v profil NA POST v API net (proverено 09.09.2026). V brauzere oni
# est. Etot skript otkryvaet stranicu Insights v OTDELNOM profile Chrome i sohranyaet to, chto
# brauzer otrisoval, v fayl proekta. Dalshe fayl razbiraet zavod - bez Vashego uchastiya.
#
# BEZOPASNOST. Otdelnyy profil Chrome (Vash osnovnoy ne trogaem), vhod odin raz rukami, odin
# zahod v sutki, tolko chtenie svoey stranicy. Nikakih kukov nikuda ne uezzhaet: profil lezhit
# u Vas, fayl - u Vas, konteyner tolko chitaet gotovyy fayl s diska.
#
# PERVYY ZAPUSK (odin raz, rukami - nuzhen vhod v akkaunt):
#     powershell -ExecutionPolicy Bypass -File tools\threads_insights.ps1 -Login
#   Otkroetsya okno Chrome - voydite v Threads, zakroyte okno.
#
# PROVERKA:
#     powershell -ExecutionPolicy Bypass -File tools\threads_insights.ps1
#   V papke data\incoming dolzhen poyavitsya fayl insights-GGGG-MM-DD.html
#
# RASPISANIE (raz v sutki, 21:00):
#     schtasks /create /tn "ThreadsInsights" /tr "powershell -ExecutionPolicy Bypass -File \"%CD%\tools\threads_insights.ps1\"" /sc daily /st 21:00

param(
    [switch]$Login,
    [string]$Url = "https://www.threads.com/insights"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$outDir = Join-Path $root "data\incoming"
$profileDir = Join-Path $env:LOCALAPPDATA "ThreadsInsights\profile"

$chrome = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $chrome) { Write-Error "Chrome ne nayden - ukazhite put v peremennoy `$chrome"; exit 1 }
New-Item -ItemType Directory -Force -Path $outDir, $profileDir | Out-Null

if ($Login) {
    Write-Host "Otkryvayu Chrome. Voydite v Threads i zakroyte okno."
    & $chrome --user-data-dir="$profileDir" "https://www.threads.com/login" | Out-Null
    exit 0
}

$stamp = Get-Date -Format "yyyy-MM-dd"
$out = Join-Path $outDir "insights-$stamp.html"

# --dump-dom otdaet UZHE OTRISOVANNUYU stranicu (SPA uspevaet zagruzit dannye za virtual-time-budget).
# Eto odin zahod, kak esli by Vy otkryli vkladku i zakryli ee.
& $chrome --headless=new --disable-gpu --user-data-dir="$profileDir" `
          --virtual-time-budget=25000 --dump-dom $Url 2>$null |
    Out-File -FilePath $out -Encoding utf8

$size = (Get-Item $out).Length
Write-Host "Snyato: $out ($size bayt)"
if ($size -lt 20000) {
    Write-Warning "Fayl podozritelno malenkiy - vozmozhno, sessiya proshla. Zapustite s -Login."
}
