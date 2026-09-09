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
#
# ZAPUSKAEM CHEREZ Start-Process, a ne cherez konveyer. Prichina (09.09.2026): Chrome pishet svoyu
# diagnostiku ("Created TensorFlow Lite XNNPACK delegate", oshibki rasshireniy) v potok OSHIBOK, a
# pri $ErrorActionPreference = "Stop" PowerShell schitaet lyuboy takoy vyvod nativnoy komandy
# terminiruyushchey oshibkoy - skript umiral do zapisi i ostavlyal fayl na 0 bayt. Start-Process s
# yavnym perenapravleniem potokov v fayly etu problemu ubiraet polnostyu.
$errFile = Join-Path $env:TEMP "threads_insights_stderr.txt"
$proc = Start-Process -FilePath $chrome -NoNewWindow -Wait -PassThru `
    -ArgumentList @("--headless=new", "--disable-gpu", "--user-data-dir=$profileDir",
                    "--virtual-time-budget=$Budget", "--dump-dom", $Url) `
    -RedirectStandardOutput $out -RedirectStandardError $errFile

if (-not (Test-Path $out)) { Write-Error "Chrome ne sozdal fayl (kod $($proc.ExitCode))"; exit 1 }
$size = (Get-Item $out).Length
$next = Set-NextRun
Write-Host "Snyato: $out ($size bayt). Sleduyushchiy zahod: $next"
if ($size -lt 20000) {
    Write-Warning "Fayl podozritelno malenkiy ($size bayt) - veroyatno, sessiya proshla ili stranica"
    Write-Warning "ne uspela otrisovatsya. Poprobuyte: -Login zanovo, libo -Now -Budget 45000."
    if (Test-Path $errFile) {
        Write-Host "--- poslednie stroki stderr Chrome ---"
        Get-Content $errFile -Tail 5
    }
}
