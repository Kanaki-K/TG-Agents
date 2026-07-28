"""Бэкап незаменимого состояния одной командой (AUDIT P2-14, N-3).

Всё перечисленное ниже — ВНЕ git (.gitignore) и живёт только на твоей машине. Потеря = катастрофа
разного масштаба (см. docs/OPERATIONS.md). Регенерируемый скретч (выгрузки, обложки, таблицы аналитики)
НАМЕРЕННО не бэкапим — он пересобирается `refresh.py` / повторной тягой.

    python backup.py                 # архив в ./backups/tg-agents-backup-<дата-время>.zip
    python backup.py "D:\\Cloud\\tg"  # архив в указанную папку (лучше — облако/внешний диск)
    python backup.py --list          # только показать классификацию (живое vs скретч), без архива

Этот файл — ЕДИНЫЙ источник правды «что незаменимо» (закрывает N-3: раньше классификация жила только
в тексте OPERATIONS.md). Меняешь состав data/ — правь списки здесь, и бэкап/доки не разъедутся.
"""
from __future__ import annotations

import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# 🔴 НЕЗАМЕНИМОЕ — бэкапим (не пересоздаётся автоматически):
IRREPLACEABLE = [
    ".env",                              # все секреты (токены, ключи, куки)
    "data/mtproto.session",             # MTProto-учётка (выгрузка + разведка + публикация)
    "data/threads_token.json",           # Threads OAuth (авто-refresh, окно 60 дней)
    "data/gpt_profile",                  # бёрнер-профиль ChatGPT (обложки флагмана)
    "data/custom_emoji.json",            # карта кастом-эмодзи (собрана руками)
    "data/cost_log.jsonl",               # история расхода (для cost-дисциплины)
    "data/run_mode.txt",                 # текущий режим (test/main)
    "data/scout_owner.txt",              # чаты владельца для проактивных отчётов
    "data/creator_owner.txt",
    "data/channel-analyst_owner.txt",
    "data/published_flagships.jsonl",    # журнал ВЫШЕДШИХ флагманов — вход Threads-дистиллятора;
                                         # датированная история (драфты эфемерны, а этот — нет)
    "data/threads_distillations.jsonl",  # журнал дистилляций (флагман→Threads-серия+категория) —
                                         # append-only вход линкера петли обучения, не пересоздать
    "data/threads_my_replies.json",      # корпус живого голоса (4966 реплик из Threads); формально
                                         # пересобирается через API, но это сотни запросов — не повторяем
    "data/psychotype_notes.md",          # ручная выжимка корпуса (17 партий через LLM) — не пересоздать
    "data/threads_psychotype.md",        # аватар голоса, синтез по всему корпусу — не пересоздать
    "memory",                            # ВСЯ обученность/состояние агентов (gitignored: уроки, банки,
]                                        # леджеры, брифы, драфты) — в репозитории её НЕТ

# 🟢 СКРЕТЧ — НЕ бэкапим (пересобирается refresh.py / повторной тягой):
SCRATCH = [
    "data/channel_posts.json", "data/channel_stats.json", "data/snapshots.json",
    "data/post_topics.json", "data/post_formats.json",
    "data/posts_analytics.csv", "data/posts_analytics.xlsx",
    "data/threads_posts.json", "data/threads_stats.json", "data/threads_topics.json",
    "data/threads_analytics.csv", "data/threads_analytics.xlsx",
    "data/source_media", "data/gpt_images", "data/incoming",
    "data/creator_last_cover.txt", "data/creator_last_kind.txt", "data/scope_last_cover.txt",
    "data/creator_pending_media.txt",
    "data/scout_seen.json",              # watermark разведки — пересоберётся следующим прогоном Скаута
    "data/.login_code_hash",
]


# Регенерируемый кэш Chromium в gpt_profile (~264МБ из 301) — браузер пересоздаёт сам. НЕ бэкапим:
# логин бёрнера держится в Cookies/Local Storage/Login Data/Preferences, их НЕ трогаем.
_CACHE_DIRS = {"Cache", "Code Cache", "GPUCache", "DawnWebGPUCache", "DawnGraphiteCache",
               "GrShaderCache", "ShaderCache", "BrowserMetrics"}


def _iter_files(rel: str):
    """Файлы под путём rel (файл → он сам; каталог → рекурсивно, минус кэш-подпапки). Пусто, если нет."""
    p = ROOT / rel
    if not p.exists():
        return
    if p.is_dir():
        yield from (f for f in p.rglob("*")
                    if f.is_file() and not (_CACHE_DIRS & set(f.relative_to(p).parts)))
    else:
        yield p


def make_backup(dest_dir: Path) -> Path:
    """Заархивировать IRREPLACEABLE в dest_dir/tg-agents-backup-<стамп>.zip. Возвращает путь архива."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    out = dest_dir / f"tg-agents-backup-{stamp}.zip"
    included, missing = [], []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in IRREPLACEABLE:
            files = list(_iter_files(rel))
            if not files:
                missing.append(rel)
                continue
            for f in files:
                z.write(f, f.relative_to(ROOT).as_posix())  # as_posix: одинаковые имена на Win/Linux
            included.append(rel)
    print(f"✅ Бэкап: {out}  ({out.stat().st_size // 1024} КБ)")
    print("   включено:", ", ".join(included) or "—")
    if missing:
        print("   ⚠ не найдено (нормально, если не используешь):", ", ".join(missing))
    print("   скретч пропущен НАМЕРЕННО (пересобирается refresh.py).")
    return out


def print_lists() -> None:
    print("🔴 НЕЗАМЕНИМОЕ (бэкапим):")
    for r in IRREPLACEABLE:
        print(f"   {'✓' if (ROOT / r).exists() else '·'} {r}")
    print("🟢 СКРЕТЧ (не бэкапим, пересоздаётся):")
    for r in SCRATCH:
        print(f"   {r}")
    # Страж рецидива N-27: новый важный файл в data/ не должен остаться невидимым для бэкапа.
    known = set(IRREPLACEABLE) | set(SCRATCH)
    data_dir = ROOT / "data"
    if data_dir.exists():
        unclassified = [f"data/{p.name}" for p in sorted(data_dir.iterdir())
                        if f"data/{p.name}" not in known and not p.name.startswith(".")]
        if unclassified:
            print("⚠ НЕ классифицировано (реши IRREPLACEABLE/SCRATCH — иначе НЕ попадёт в бэкап):")
            for u in unclassified:
                print(f"   ? {u}")


def main() -> int:
    args = sys.argv[1:]
    if "--list" in args:
        print_lists()
        return 0
    dest = Path(args[0]) if args else ROOT / "backups"
    make_backup(dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
