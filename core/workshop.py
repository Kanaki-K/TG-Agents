"""Мастерская Разработчика: безопасные операции над определениями агентов.

Разработчик улучшает других сотрудников команды, правя их «личность» (SKILL.md).
Принцип безопасности (см. PLAN.md §5 «не мутируем живого»):

  1. propose()  — пишет ПРЕДЛОЖЕНИЕ в SKILL.proposed.md и возвращает diff (живой
                  SKILL.md при этом не трогается);
  2. владелец смотрит diff и одобряет изменение в чате;
  3. apply()    — делает бэкап текущей версии в .history/ и промоутит предложение
                  в боевой SKILL.md.

Откат — rollback() из последнего бэкапа. Версионная история целиком — в Git.
Структурная гарантия: apply() работает ТОЛЬКО если есть .proposed-файл, то есть
каждое применённое изменение было сначала показано владельцу как diff.
"""
from __future__ import annotations

import difflib
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
AGENTS = ROOT / "agents"

PROPOSED = "SKILL.proposed.md"
HISTORY = ".history"
MAX_DIFF = 3000  # символов; длинный diff обрезаем, чтобы не раздувать ответ


def _ts() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _agent_dir(name: str) -> Path:
    """Папка агента с защитой от выхода за пределы agents/."""
    if not name or "/" in name or "\\" in name or ".." in name:
        raise ValueError(f"Недопустимое имя агента: {name!r}")
    d = AGENTS / name
    if not (d / "SKILL.md").exists():
        raise ValueError(f"Агент '{name}' не найден (нет agents/{name}/SKILL.md).")
    return d


def _title(skill_text: str) -> str:
    """Первая непустая строка SKILL.md как название."""
    for line in skill_text.splitlines():
        line = line.strip()
        if line:
            return line.lstrip("# ").strip()
    return ""


def _diff(old: str, new: str, name: str) -> str:
    lines = difflib.unified_diff(
        old.splitlines(), new.splitlines(),
        fromfile=f"{name}/SKILL.md (текущая)",
        tofile=f"{name}/SKILL.md (предложение)",
        lineterm="",
    )
    text = "\n".join(lines)
    if len(text) > MAX_DIFF:
        text = text[:MAX_DIFF] + "\n… (diff обрезан, изменений больше)"
    return text or "(изменений нет)"


def list_agents() -> str:
    """Список агентов команды: имя, роль, модель, есть ли непринятое предложение."""
    rows = []
    for d in sorted(AGENTS.iterdir()):
        skill = d / "SKILL.md"
        if not skill.exists():
            continue
        title = _title(skill.read_text(encoding="utf-8"))
        model = ""
        cfg = d / "config.yaml"
        if cfg.exists():
            c = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
            model = c.get("model", "")
        pending = "  ⟵ есть неприменённое предложение" if (d / PROPOSED).exists() else ""
        rows.append(f"- {d.name}: {title} (модель: {model}){pending}")
    return "\n".join(rows) or "Агентов не найдено."


def read_agent(name: str) -> str:
    """Текущее определение агента: config.yaml + SKILL.md (личность)."""
    d = _agent_dir(name)
    cfg = d / "config.yaml"
    cfg_text = cfg.read_text(encoding="utf-8") if cfg.exists() else "(нет config.yaml)"
    skill = (d / "SKILL.md").read_text(encoding="utf-8")
    return f"# config.yaml\n{cfg_text}\n\n# SKILL.md (личность)\n{skill}"


def propose(name: str, new_skill: str, rationale: str = "") -> str:
    """Сохранить ПРЕДЛОЖЕНИЕ новой версии SKILL.md и вернуть diff. Живой файл не трогаем."""
    d = _agent_dir(name)
    current = (d / "SKILL.md").read_text(encoding="utf-8")
    if new_skill.strip() == current.strip():
        return "Предложение совпадает с текущей версией — менять нечего."
    (d / PROPOSED).write_text(new_skill, encoding="utf-8")
    head = f"Предложение для '{name}' сохранено (боевой SKILL.md пока не тронут).\n"
    if rationale:
        head += f"Обоснование: {rationale}\n"
    head += ("\nПокажи владельцу diff ниже и дождись его ЯВНОГО одобрения, "
             "прежде чем вызывать apply_improvement:\n\n")
    return head + _diff(current, new_skill, name)


def show_proposal(name: str) -> str:
    """Показать diff неприменённого предложения по агенту."""
    d = _agent_dir(name)
    prop = d / PROPOSED
    if not prop.exists():
        return f"Для '{name}' нет неприменённого предложения."
    current = (d / "SKILL.md").read_text(encoding="utf-8")
    return _diff(current, prop.read_text(encoding="utf-8"), name)


def apply(name: str) -> str:
    """Промоутить предложение в боевой SKILL.md. Только после одобрения владельца!"""
    d = _agent_dir(name)
    prop = d / PROPOSED
    if not prop.exists():
        return (f"Для '{name}' нет предложения. Сначала вызови propose_improvement "
                "и получи одобрение владельца.")
    new = prop.read_text(encoding="utf-8")
    current = (d / "SKILL.md").read_text(encoding="utf-8")
    hist = d / HISTORY
    hist.mkdir(exist_ok=True)
    backup = hist / f"SKILL.{_ts()}.md"
    backup.write_text(current, encoding="utf-8")
    (d / "SKILL.md").write_text(new, encoding="utf-8")
    prop.unlink()
    return (f"Готово: новая версия '{name}' применена. "
            f"Прежняя сохранена в {HISTORY}/{backup.name} (откат — rollback_agent). "
            f"⚠️ Перезапусти этого агента, чтобы изменения вступили в силу.")


def discard(name: str) -> str:
    """Отбросить неприменённое предложение."""
    d = _agent_dir(name)
    prop = d / PROPOSED
    if prop.exists():
        prop.unlink()
        return f"Предложение для '{name}' отброшено."
    return f"Для '{name}' нет предложения."


def rollback(name: str) -> str:
    """Откатить SKILL.md к последней сохранённой версии из .history/."""
    d = _agent_dir(name)
    hist = d / HISTORY
    backups = sorted(hist.glob("SKILL.*.md")) if hist.exists() else []
    if not backups:
        return f"Для '{name}' нет сохранённых версий для отката."
    last = backups[-1]
    (d / "SKILL.md").write_text(last.read_text(encoding="utf-8"), encoding="utf-8")
    last.unlink()
    return (f"Откатил '{name}' к версии {last.name}. "
            f"⚠️ Перезапусти этого агента, чтобы откат вступил в силу.")
