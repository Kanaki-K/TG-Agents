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
#
# SOBRAT VSYU OCHERED ZA DEN (~2-3 chasa, s pereryvami; okno PowerShell ne zakryvat):
#     powershell -ExecutionPolicy Bypass -File tools\threads_insights.ps1 -Now -All
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
    [switch]$All,
    [int]$Batch = 20,
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

# CHISTKA PERED RABOTOY. Nash headless-Chrome mozhet ostatsya visеt posle Ctrl+C (zhivoy sluchay
# 09.09: docherniy process perezhil PowerShell). Snimaem ego sami i idem dalshe.
#
# ZDES NET OTKAZA "profil zanyat". Ran'she skript v etom sluchae vyhodil - i vladelec upiralsya v
# soobshchenie "zakroyte okno", kogda zakryvat bylo nechego: okna u zavisshego processa net.
# Otkaz zdes voobshche ne nuzhen: esli profil deystvitelno zanyat, Chrome prosto ne otdast stranicu,
# i eto uvidit obychnaya proverka razmera fayla nizhe. Luchshe poprobovat i uznat, chem ne nachat.
Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -like "*ThreadsInsights*" -and
                   $_.CommandLine -like "*--headless*" } |
    ForEach-Object {
        Write-Host "Ubirayu zavisshiy fonovyy Chrome (PID $($_.ProcessId)) ot proshloy sessii."
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
Start-Sleep -Seconds 2

$stamp = Get-Date -Format "yyyy-MM-dd"
$out = Join-Path $outDir "insights-$stamp.html"

function Get-Page {
    # Odin snimok odnoy stranicy v fayl. Yazyk interfeysa prinuditelno russkiy: svezhiy profil
    # headless otdaval nemeckiy, a razbor idet po SLOVAM interfeysa - pust oni budut predskazuemy.
    param([string]$PageUrl, [string]$Target, [int]$TimeoutSec = 120)
    $errFile = Join-Path $env:TEMP "threads_insights_stderr.txt"
    # -PassThru bez -Wait + WaitForExit s TAYMAUTOM. Prichina (zhivoy zapusk 09.09): Chrome zavis na
    # odnoy stranice, fayl ostalsya na 0 bayt, i skript zhdal ego vechno - sessiya vstala nasmert.
    # Teper zavisshiy Chrome ubivaetsya, stranica schitaetsya nesnyatoy i my idem dalshe.
    $proc = Start-Process -FilePath $chrome -NoNewWindow -PassThru `
        -ArgumentList @("--headless=new", "--disable-gpu", "--user-data-dir=$profileDir",
                        "--lang=ru", "--accept-lang=ru-RU,ru",
                        "--virtual-time-budget=$Budget", "--dump-dom", $PageUrl) `
        -RedirectStandardOutput $Target -RedirectStandardError $errFile
    if (-not $proc.WaitForExit($TimeoutSec * 1000)) {
        Write-Warning "Chrome zavis na $PageUrl - ubivayu i idu dalshe."
        try { $proc.Kill() } catch { }
        Start-Sleep -Seconds 5
        return 0
    }
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
    # Peremennaya NE $all: v PowerShell imena registro-nezavisimy, i $all zatiraet klyuch -All
    # (svitch prevrashchaetsya v massiv strok i skript padaet na starte). Poymano na zhivom zapuske.
    $queue = Get-Content $queueFile | Where-Object { $_.Trim() }
    # -All: vsya ochered za odin den (reshenie vladelca 09.09 - "nuzhno za segodnya sobrat 90
    # postov"). Bez flaga - obychnyy korotkiy zahod.
    $codes = if ($All) { $queue } else { $queue | Select-Object -First $Posts }
}

$done = 0
$stopped = $false
$inBatch = 0
$misses = 0
foreach ($code in $codes) {
    # Pauza mezhdu postami. V obychnom rezhime 60-180 sekund: eto ne "vezhlivost k serveru", a
    # edinstvennoe otlichie ot robota - chelovek smotrit statistiku posta poltory minuty.
    # V rezhime -All pauza korotkaya (20-50 s), no zato posle kazhdyh $Batch postov idet BOLSHOY
    # pereryv 20-40 minut. Eto pohozhe na cheloveka, kotoryy sadilsya za statistiku neskolko raz
    # za den, a ne na robota, ravnomerno stuchashchego 80 raz podryad.
    if ($All) {
        Start-Sleep -Seconds (Get-Random -Minimum 20 -Maximum 51)
        $inBatch++
        if ($inBatch -ge $Batch) {
            $pause = Get-Random -Minimum 1200 -Maximum 2401
            Write-Host "  ...pereryv $([int]($pause/60)) min (snyato $done iz $($codes.Count))"
            Start-Sleep -Seconds $pause
            $inBatch = 0
        }
    } else {
        Start-Sleep -Seconds (Get-Random -Minimum 60 -Maximum 181)
    }

    $target = Join-Path $outDir "insights-post-$code-$stamp.html"
    $n = Get-Page -PageUrl "https://www.threads.com/insights/post/$code" -Target $target
    if ($n -lt 1000) {
        # Odna pustaya stranica - byvaet (zavis Chrome, ne uspela otrisovka). DVE PODRYAD - eto uzhe
        # priznak, chto nas ne hotyat obsluzhivat, i sessiya konchaetsya bez povtorov: retray v
        # oshibku - imenno to, chem my odnazhdy uzhe navredili akkauntu (razbor 14.07.2026).
        Remove-Item $target -ErrorAction SilentlyContinue
        $misses++
        Write-Warning "Stranica posta $code ne snyalas ($misses podryad)."
        if ($misses -ge 2) { Write-Warning "Dve podryad - ostanavlivayu sessiyu."; $stopped = $true; break }
        continue
    }
    $misses = 0
    $done++
    if ($done % 10 -eq 0) { Write-Host "  snyato $done iz $($codes.Count)" }
}

# Sleduyushchiy zahod. Poka ochered dlinnaya - raz v sutki (v sluchaynyy chas): tak 90 dney
# naberutsya za paru nedel. Kogda dogonim - perehodim na redkiy temp 3-5 sutok, kak prosil
# vladelec. Posle strannogo otveta - pauza podlinnee, chtoby ne davit.
$left = if (Test-Path $queueFile) { (Get-Content $queueFile | Where-Object { $_.Trim() }).Count } else { 0 }
# Posle -All ochered v fayle eshche staraya (ee peresobiraet zavod, kogda razberet snimki),
# poetomu po $left sudit nelzya: reshaem po rezhimu. Sobrali vse za den - dalshe redkiy temp,
# kak prosil vladelec ("sleduyushchie sessii budut raz v 3 dnya").
if ($stopped)             { $next = Set-NextRun -MinD 3 -MaxD 5 }
elseif ($All)             { $next = Set-NextRun -MinD $MinDays -MaxD $MaxDays }
elseif ($left -gt $Posts) { $next = Set-NextRun -MinD 1 -MaxD 1 }
else                      { $next = Set-NextRun -MinD $MinDays -MaxD $MaxDays }

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
