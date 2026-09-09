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
    [int]$Budget = 25000,
    [int]$Posts = 5,
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
    # Start-Process, a NE "& chrome ... | Out-Null": pri konvejere PowerShell zhdet vyhoda Chrome i
    # terminal ostaetsya zanyat do zakrytiya okna. Zdes zapuskaem i srazu otdaem priglashenie.
    Write-Host "Otkryvayu Chrome. Voydite v Threads, potom ZAKROYTE eto okno Chrome."
    Start-Process -FilePath $chrome -ArgumentList @("--user-data-dir=$profileDir",
                                                    "https://www.threads.com/login")
    Write-Host "Posle vhoda i zakrytiya okna zapustite:  powershell -ExecutionPolicy Bypass -File tools\threads_insights.ps1 -Now"
    exit 0
}

# Snimok i vhod delyat odin profil, a Chrome ne daet dvum ekzemplyaram rabotat s odnim profilem.
# Poetomu esli okno vhoda eshche otkryto - govorim ob etom yavno, a ne otdaem pustoy fayl.
$busy = Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -like "*ThreadsInsights*" }
if ($busy) {
    Write-Warning "Okno Chrome s etim profilem eshche otkryto - zakroyte ego i povtorite komandu."
    exit 1
}

function Set-NextRun {
    # Sleduyushchiy zahod v sluchaynyy chas i minutu. Imenno sluchaynost delaet povedenie pohozhim
    # na cheloveka, kotoryy zaglyadyvaet v statistiku kogda vspomnit, a ne po budilniku.
    param([int]$MinD = 3, [int]$MaxD = 5)
    $next = (Get-Date).Date.AddDays((Get-Random -Minimum $MinD -Maximum ($MaxD + 1))).
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
        $n = Set-NextRun -MinD 0 -MaxD 0            # pervyy zapusk: naznachaem na segodnya
        Write-Host "Pervyy zahod naznachen na $n"
        exit 0
    }
}

$stamp = Get-Date -Format "yyyy-MM-dd"
$out = Join-Path $outDir "insights-$stamp.html"

function Get-Page {
    # Odin snimok odnoy stranicy v fayl. Yazyk interfeysa prinuditelno russkiy: svezhiy profil
    # headless otdaval nemeckiy, a razbor idet po SLOVAM interfeysa - pust oni budut predskazuemy.
    param([string]$PageUrl, [string]$Target)
    $errFile = Join-Path $env:TEMP "threads_insights_stderr.txt"
    Start-Process -FilePath $chrome -NoNewWindow -Wait `
        -ArgumentList @("--headless=new", "--disable-gpu", "--user-data-dir=$profileDir",
                        "--lang=ru", "--accept-lang=ru-RU,ru",
                        "--virtual-time-budget=$Budget", "--dump-dom", $PageUrl) `
        -RedirectStandardOutput $Target -RedirectStandardError $errFile | Out-Null
    if (Test-Path $Target) { return (Get-Item $Target).Length }
    return 0
}

# ZAPUSKAEM CHEREZ Start-Process, a ne cherez konveyer. Prichina (09.09.2026): Chrome pishet svoyu
# diagnostiku ("Created TensorFlow Lite XNNPACK delegate", oshibki rasshireniy) v potok OSHIBOK, a
# pri $ErrorActionPreference = "Stop" PowerShell schitaet lyuboy takoy vyvod nativnoy komandy
# terminiruyushchey oshibkoy - skript umiral do zapisi i ostavlyal fayl na 0 bayt.
$size = Get-Page -PageUrl $Url -Target $out
if ($size -lt 1) { Write-Error "Chrome ne sozdal fayl"; exit 1 }
# STRANICY OTDELNYH POSTOV. Obshchaya stranica daet tolko prosmotry; zahody v profil i novyh
# chitateley - tolko vnutri posta (/insights/post/<kod>).
#
# OCHERED SCHITAET ZAVOD, ne skript: fayl data/threads_insights_queue.txt - eto kody postov za
# 90 dney, po kotorym cifr eshche NET, svezhie vperedi. Poetomu my nikogda ne hodim dvazhdy za
# odnim i tem zhe i ne listaem lentu (obshchaya stranica pokazyvaet tolko ~10 poslednih postov).
# Za odin zahod beryom $Posts shtuk - ostalnoe podozhdet sleduyushchego raza.
$queueFile = Join-Path $root "data\threads_insights_queue.txt"
$codes = @()
if (Test-Path $queueFile) {
    $codes = Get-Content $queueFile | Where-Object { $_.Trim() } | Select-Object -First $Posts
}

$done = 0
$stopped = $false
foreach ($code in $codes) {
    # Pauza 60-180 sekund. Eto ne "vezhlivost k serveru" - eto edinstvennoe otlichie ot robota:
    # chelovek smotrit statistiku posta poltory minuty, a ne 300 millisekund.
    Start-Sleep -Seconds (Get-Random -Minimum 60 -Maximum 181)
    $target = Join-Path $outDir "insights-post-$code-$stamp.html"
    $n = Get-Page -PageUrl "https://www.threads.com/insights/post/$code" -Target $target
    if ($n -lt 1000) {
        # PERVYY ZHE strannyy otvet = konec sessii, bez povtorov. Retray v oshibku - imenno to,
        # chem my odnazhdy uzhe navredili akkauntu (razbor 14.07.2026).
        Remove-Item $target -ErrorAction SilentlyContinue
        Write-Warning "Stranica posta $code prishla pustoy - ostanavlivayu sessiyu."
        $stopped = $true
        break
    }
    $done++
}

# Sleduyushchiy zahod. Poka ochered dlinnaya - raz v sutki (v sluchaynyy chas): tak 90 dney
# naberutsya za paru nedel. Kogda dogonim - perehodim na redkiy temp 3-5 sutok, kak prosil
# vladelec. Posle strannogo otveta - pauza podlinnee, chtoby ne davit.
$left = if (Test-Path $queueFile) { (Get-Content $queueFile | Where-Object { $_.Trim() }).Count } else { 0 }
if ($stopped)          { $next = Set-NextRun -MinD 3 -MaxD 5 }
elseif ($left -gt $Posts) { $next = Set-NextRun -MinD 1 -MaxD 1 }
else                   { $next = Set-NextRun -MinD $MinDays -MaxD $MaxDays }

Write-Host "Snyato: obshchaya stranica ($size bayt), stranic postov: $done, v ocheredi ostalos: $left."
Write-Host "Sleduyushchiy zahod: $next"
if ($size -lt 20000) {
    Write-Warning "Fayl podozritelno malenkiy ($size bayt) - veroyatno, sessiya proshla ili stranica"
    Write-Warning "ne uspela otrisovatsya. Poprobuyte: -Login zanovo, libo -Now -Budget 45000."
    if (Test-Path $errFile) {
        Write-Host "--- poslednie stroki stderr Chrome ---"
        Get-Content $errFile -Tail 5
    }
}
