"""Загрузка настроек: секреты из .env + конфиг конкретного агента."""
from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def get_secret(name: str) -> str:
    """Достать секрет из .env. Падаем с понятным сообщением, если пусто."""
    value = (os.getenv(name) or "").strip()
    if not value:
        raise RuntimeError(
            f"В файле .env не задан {name}. Открой .env и впиши значение."
        )
    return value


def get_optional(name: str) -> str:
    """Секрет, которого может и не быть (пустая строка, если не задан)."""
    return (os.getenv(name) or "").strip()


_owner_warned = False  # чтобы предупреждение о невалидном OWNER_ID не спамило на каждое сообщение


def owner_ids() -> set[int]:
    """Разрешённые Telegram user-id (владелец + при нужде свои боты для bot-to-bot).

    Берём из .env OWNER_ID — одно число или несколько через запятую. Пусто = гейт ВЫКЛЮЧЕН
    (бот отвечает всем) — стартовый рантайм об этом громко предупреждает. Узнать свой id: /whoami.
    """
    global _owner_warned
    raw = (os.getenv("OWNER_ID") or "").strip()
    ids: set[int] = set()
    dropped: list[str] = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if part.isdigit():
            ids.add(int(part))
        else:
            dropped.append(part)
    # Тихое открытие бота — реальный риск (N-13): OWNER_ID задан, но весь мусор → ids пусто → гейт молча
    # выкл. Предупреждаем ОДИН раз за процесс (owner_ids зовётся на каждое сообщение — не спамим).
    if not _owner_warned and (dropped or (raw and not ids)):
        if dropped:
            logging.warning("[owner_ids] OWNER_ID: пропущены нечисловые части %s — проверь настройку", dropped)
        if raw and not ids:
            logging.warning("[owner_ids] OWNER_ID задан, но НИ ОДИН id не валиден → гейт ОТКРЫТ всем!")
        _owner_warned = True
    return ids


def agent_api_key(cfg: dict) -> str:
    """Ключ Claude для агента: свой (cfg['api_key_env']) или общий ANTHROPIC_API_KEY."""
    env = cfg.get("api_key_env")
    if env:
        own = get_optional(env)
        if own:
            return own
    return get_secret("ANTHROPIC_API_KEY")


def load_agent(name: str) -> dict:
    """Загрузить агента: его конфиг (config.yaml) + личность (SKILL.md)."""
    agent_dir = ROOT / "agents" / name
    with open(agent_dir / "config.yaml", "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["persona"] = (agent_dir / "SKILL.md").read_text(encoding="utf-8")
    return cfg
