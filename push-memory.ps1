# push-memory.ps1 — одна кнопка: бэкап приватной ПАМЯТИ в tg-agents-memory.
# Запуск: правый клик → "Run with PowerShell", ИЛИ в терминале:
#   powershell -ExecutionPolicy Bypass -File .\push-memory.ps1
# Что делает: заходит в memory/, коммитит изменения (если есть) и пушит. Код НЕ трогает.

$ErrorActionPreference = "Stop"
$mem = Join-Path $PSScriptRoot "memory"
if (-not (Test-Path (Join-Path $mem ".git"))) {
    Write-Host "СТОП: memory/ не git-репо ($mem). Инициализируй сначала." -ForegroundColor Red
    exit 1
}
Set-Location $mem

# СТРАХОВКА: пушим ТОЛЬКО в приватный memory-репо. Если origin = публичный код — стоп (утечка IP).
$origin = (git remote get-url origin).Trim()
if ($origin -notmatch "tg-agents-memory") {
    Write-Host "СТОП: origin памяти = '$origin', ожидался tg-agents-memory. НЕ пушу (защита от утечки в публичный репо)." -ForegroundColor Red
    exit 1
}

git add -A
if (git status --porcelain) {
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm"
    git commit -m "chore(memory): снапшот $stamp"
    Write-Host "Закоммитил изменения памяти." -ForegroundColor Green
} else {
    Write-Host "Изменений в памяти нет — коммитить нечего, просто синхронизирую." -ForegroundColor Yellow
}

git push
Write-Host "ГОТОВО: память забэкаплена в tg-agents-memory (приватный)." -ForegroundColor Green
