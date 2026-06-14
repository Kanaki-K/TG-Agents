"""Загрузка настроек: секреты из .env + конфиг конкретного агента."""
from __future__ import annotations

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


def load_agent(name: str) -> dict:
    """Загрузить агента: его конфиг (config.yaml) + личность (SKILL.md)."""
    agent_dir = ROOT / "agents" / name
    with open(agent_dir / "config.yaml", "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["persona"] = (agent_dir / "SKILL.md").read_text(encoding="utf-8")
    return cfg
