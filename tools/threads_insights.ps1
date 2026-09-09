# threads_insights.ps1 - snimok stranicy Insights Vashim zhe Chrome, raz v 3-5 dney.
#
# ZACHEM. Podpisok i zahodov v profil NA POST v API net (provereno 09.09.2026). V brauzere oni
# est. Skript otkryvaet stranicu Insights v OTDELNOM profile Chrome i sohranyaet to, chto brauzer
# otrisoval, v fayl proekta. Dalshe fayl razbiraet zavod - bez Vashego uchastiya.
#
# TEMP (reshenie vladelca 09.09.2026): "ne nuzhno raz v sutki, dostatochno 1 raz v 3 dnya v
# randomnoe vremya". Poetomu zadacha zapuskaetsya KAZHDYY CHAS, no skript pochti vsegda vyhodit
# srazu: on hranit vremya sleduyushchego zahoda i zhdet ego. Interval - sluchaynyy 3-5 dney,
# chas i minuta - sluchaynye. Rovnyy ritm viden so storony, sluchaynyy - net; i zahodov stanovitsya
# v 4 raza menshe, chem pri ezhednevnom snimke.
#
# BEZOPASNOST. Otdelnyy profil Chrome (osnovnoy ne trogaem), vhod odin raz rukami, tolko chtenie
# svoey stranicy. Kuki nikuda ne uezzhayut: profil, fayl i brauzer ostayutsya u Vas. Zavod chitaet
# gotovyy fayl s diska - sam v Meta ne hodit.
#
# PERVYY ZAPUSK (odin raz, rukami - nuzhen vhod v akkaunt):
#     powershell -ExecutionPolicy Bypass -File tools\threads_insights.ps1 -Login
#   Otkroetsya okno Chrome - voydite v Threads, zakroyte okno.
#
# PROVERKA SEYCHAS (ignoriruet raspisanie):
#     powershell -ExecutionPolicy Bypass -File tools\threads_insights.ps1 -Now
#   V papke data\incoming dolzhen poyavitsya fayl insights-GGGG-MM-DD.html
#
# RASPISANIE (kazhdyy chas; skript sam reshaet, pora li). V terminale PyCharm (PowerShell):
#     $cmd = 'powershell -ExecutionPolicy Bypass -File "' + $PWD + '\tools\threads_insights.ps1"'
#     schtasks /create /tn "ThreadsInsights" /tr $cmd /sc hourly /f
#   Proverit:  schtasks /query /tn "ThreadsInsights"
#   Ubrat:     schtasks /delete /tn "ThreadsInsights" /f

param(
    [switch]$Login,
    [switch]$Now,
    [int]$MinDays = 3,
    [int]$MaxDays = 5,
    [string]$Url = "https://www.threads.com/insights"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$outDir = Join-Path $root "data\incoming"
$stateFile = Join-Path $root "data\threads_insights_next.txt"
$profileDir = Join-Path $env:LOCALAPPDATA "ThreadsInsights\profile"

$chrome = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $chrome) { Write-Error "Chrome ne nayden"; exit 1 }
New-Item -ItemType Directory -Force -Path $outDir, $profileDir | Out-Null

if ($Login) {
    Write-Host "Otkryvayu Chrome. Voydite v Threads i zakroyte okno."
    & $chrome --user-data-dir="$profileDir" "https://www.threads.com/login" | Out-Null
    exit 0
}

function Set-NextRun {
    # Sleduyushchiy zahod: cherez 3-5 sutok, v sluchaynyy chas i minutu. Imenno sluchaynost
    # delaet povedenie pohozhim na cheloveka, kotoryy zaglyadyvaet v statistiku kogda vspomnit.
    $next = (Get-Date).Date.AddDays((Get-Random -Minimum $MinDays -Maximum ($MaxDays + 1))).
            AddHours((Get-Random -Minimum 9 -Maximum 23)).
            AddMinutes((Get-Random -Minimum 0 -Maximum 60))
    $next.ToString("o") | Out-File -FilePath $stateFile -Encoding ascii
    return $next
}

if (-not $Now) {
    if (Test-Path $stateFile) {
        $next = [datetime]::Parse((Get-Content $stateFile -Raw).Trim())
        if ((Get-Date) -lt $next) { exit 0 }        # eshche ne pora - vyhodim molcha
    } else {
        $n = Set-NextRun                            # pervyy zapusk: tolko naznachaem vremya
        Write-Host "Pervyy zahod naznachen na $n"
        exit 0
    }
}

$stamp = Get-Date -Format "yyyy-MM-dd"
$out = Join-Path $outDir "insights-$stamp.html"

# --dump-dom otdaet UZHE OTRISOVANNUYU stranicu. Eto odin zahod, kak esli by Vy otkryli vkladku.
& $chrome --headless=new --disable-gpu --user-data-dir="$profileDir" `
          --virtual-time-budget=25000 --dump-dom $Url 2>$null |
    Out-File -FilePath $out -Encoding utf8

$size = (Get-Item $out).Length
$next = Set-NextRun
Write-Host "Snyato: $out ($size bayt). Sleduyushchiy zahod: $next"
if ($size -lt 20000) {
    Write-Warning "Fayl podozritelno malenkiy - vozmozhno, sessiya proshla. Zapustite s -Login."
}
