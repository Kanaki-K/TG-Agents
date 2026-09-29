"""Каждый прямой вызов Claude пишется в журнал расходов (аудит кэша 28.09.2026).

Письмо Anthropic про кэш считало трафик, которого в data/cost_log.jsonl не было: обогащение постов
(connectors/enrich_common.py) ходило в API мимо cost.record. Аудит расходов по неполному журналу
врёт — этот страж не даёт появиться новому вызову без учёта. core/llm.py пишет расход сам."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIP = {"tests", ".venv", "venv", ".git"}


def test_every_direct_api_call_records_cost():
    missing = []
    for f in ROOT.rglob("*.py"):
        if SKIP & set(f.relative_to(ROOT).parts) or f.name == "llm.py":
            continue
        lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()
        for i, ln in enumerate(lines):
            if re.search(r"\.messages\.create\(", ln) and not ln.lstrip().startswith("#"):
                window = "\n".join(lines[i:i + 15])
                if "cost.record(" not in window:
                    missing.append(f"{f.relative_to(ROOT)}:{i + 1}")
    assert not missing, f"вызовы Claude мимо журнала расходов: {missing}"


def test_opus_5_has_its_own_rate():
    from core import cost
    assert cost.RATES["claude-opus-5"] == (5.0, 25.0)
