# Операционка: бэкапы и «жив ли завод»

Короткий рунбук для владельца. Закрывает AUDIT N-5/P2-14 (бэкап невосстановимого) и «упавший бот молча мёртв».

## 🔴 Невосстановимые файлы — БЭКАПИТЬ РЕГУЛЯРНО

Всё это вне git (в `.gitignore`) и живёт только на твоей машине. Потеря = катастрофа разного масштаба:

| Файл | Что на нём | Потеря = |
|---|---|---|
| `data/evgeniyp.session` | MTProto-учётка (бёрнер) | вся выгрузка канала + разведка ТГ + **публикация**. Восстановление = повторный логин по SMS + риск для аккаунта |
| `.env` | все секреты (токены ботов, API-ключи, X-куки, CMC) | завод не стартует; перевыпуск всех ключей |
| `data/threads_token.json` | Threads-токен (авто-refresh) | доступ к Threads; нужен повторный OAuth-бутстрап (окно refresh 60 дней) |
| `data/gpt_profile/` | бёрнер-профиль ChatGPT (обложки флагмана) | повторный логин в веб-ChatGPT |
| `memory/` (живое) | `scope_lessons.md`, `post_lessons.md`, `headline_bank.md`, `x_authors.json`, `tasks.json`, `journal/` | обученность агентов и состояние (gitignored — в репо их НЕТ) |

> `data/x_cookies.json` (если используешь файл вместо .env) — тоже сюда; протухает раз в недели, перевзять из браузера.

## Как бэкапить (PowerShell, Windows)

Раз в неделю (или после правок памяти) — архив критичного в **офф-машинное** место (облако/внешний диск):

```powershell
$stamp = Get-Date -Format "yyyy-MM-dd"
$dst = "$HOME\Backups\tg-agents"           # ← замени на облачную папку / внешний диск
New-Item -ItemType Directory -Force $dst | Out-Null
Compress-Archive -Path .env, data\evgeniyp.session, data\threads_token.json, data\gpt_profile, memory `
                 -DestinationPath "$dst\tg-agents-$stamp.zip" -Force
Write-Host "Бэкап: $dst\tg-agents-$stamp.zip"
```

Держи 2-3 последних архива. **Проверь восстановление хоть раз** (распакуй в чистую папку, запусти `--draft-only`).

## Как понять, что завод ЖИВ (silent-failure чек)

Боты/пайплайн падают молча. Быстрая проверка:

```powershell
# 1) был ли расход за последние сутки (если пусто — ничего не гонялось)
Get-Content data\cost_log.jsonl -Tail 3

# 2) свежесть последнего брифа и драфта (старьё = разведка/письмо встали)
Get-ChildItem memory\briefs\*.md, memory\drafts\*.md | Sort LastWriteTime -Desc | Select -First 2 Name, LastWriteTime

# 3) сухой прогон без публикации — «всё ли живо end-to-end»
python run_pipeline.py --scope --draft-only
```

Признаки тихого отказа: `/scan` пишет «⚠ X недоступен» (протухли куки → перевзять), нет свежих брифов в дни разведки (Пн/Вт/Чт), пустой `cost_log` за сутки при ожидаемых прогонах.

## Восстановление

- `.env` / `data/*` — распаковать архив на место (пути НЕ менять — `*.session` привязана к пути).
- `memory/` (в git-части) — из репозитория; живая часть (уроки/леджер/задачи) — только из бэкапа.
