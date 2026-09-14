"""ЖИВАЯ РЕЧЬ И ФИНАЛ SCOPE (14.09.2026) — правки владельца к посту «AI-боссы просят притормозить гонку».

ЗАЧЕМ. Владелец переписал заголовок, снял «Но честно:» и оба последних абзаца: «нахуй этот долгосрочник» и
«какая педаль нахуй, какую сторону». Потом: «проверка должна быть ещё на то — говорят ли так люди». Код
ловит то, что меряется списком (штампы, слово завода, антитеза в финале); остальное показывает отдельный
читатель, а переписывает писатель. Без сети и LLM.
Запуск: python -m pytest tests/test_scope_speech.py"""
from __future__ import annotations

import inspect

import run_pipeline as rp
from core import creator_tools as ct, scope_writer as sw, topic_gate as tg

FOOT = ("🖥 [Канал](https://t.me/+WZvj-M2zzt0xMjFi) | ▶️ [Медиа](https://linktr.ee/Kanaki.Crypto) | "
        "🥸 [Мемы](https://t.me/+isK3TfonMlYzNTAy) | 📱 [Notion](https://www.notion.so/Education-1711c6d11f3380f993e9d089e7eb724c?pvs=4)")


def _post(*paras: str) -> str:
    return "**⚠️ AI-боссы просят притормозить гонку, которую сами и начали**\n\n" + "\n\n".join(paras) + "\n\n" + FOOT


# ── код: штампы, слово завода, антитеза в финале ─────────────────────────────────────────────────

def test_lead_stamp_is_flagged():
    _, warns = ct._lint(_post("12 сентября вышло эссе", "Но честно: это гипотеза Хейса, а не сценарий"), "scope")
    assert any("вводная-ШТАМП «честно»" in w for w in warns)


def test_honestly_inside_a_sentence_is_live_speech():
    _, warns = ct._lint(_post("12 сентября вышло эссе", "Я, честно говоря, такого не ждал от рынка"), "scope")
    assert not any("вводная-ШТАМП" in w for w in warns)


def test_factory_word_is_flagged_but_the_adjective_is_not():
    _, warns = ct._lint(_post("Эссе вышло 12 сентября", "Для долгосрочника это ничего не меняет"), "scope")
    assert any("слово завода «долгосрочника»" in w for w in warns)
    _, warns = ct._lint(_post("Эссе вышло 12 сентября", "Долгосрочный план это не меняет"), "scope")
    assert not any("слово завода" in w for w in warns)


def test_finale_antithesis_of_14_09_is_a_defect():
    machine = "Для долгосрочника ставка не на то, победит ли ИИ, а на то, чем в любом случае будут гасить его долги"
    owner = "Взлетит AI или лопнет - долги под него уже набраны, и гасить их будут новыми деньгами"
    assert any("АНТИТЕЗЕ" in d for d in ct._finale_defects(machine))
    assert not any("АНТИТЕЗЕ" in d for d in ct._finale_defects(owner))


# ── читатель речи ───────────────────────────────────────────────────────────────────────────────

def test_speech_flags_parse_only_quoted_findings(monkeypatch):
    answer = ("Нашёл вот что:\n"
              "«у станка одна педаль» — образ, надо разгадывать — «в любом случае включат станок»\n"
              "- «Но честно:» — вводная-штамп — просто «Это гипотеза»\n"
              "Остальное живое.")
    monkeypatch.setattr(sw.llm, "reply", lambda *a, **k: (answer, None))
    monkeypatch.setattr(sw.cost, "set_context", lambda *a, **k: None)
    flags = sw.speech_flags(_post("Текст поста"), api_key="k")
    assert len(flags) == 2 and flags[0].startswith("«у станка") and flags[1].startswith("«Но честно")


def test_speech_flags_clean_and_footer_is_not_sent(monkeypatch):
    seen = {}

    def reply(model, system, hist, user, *a, **k):
        seen["user"] = user
        return "чисто", None

    monkeypatch.setattr(sw.llm, "reply", reply)
    monkeypatch.setattr(sw.cost, "set_context", lambda *a, **k: None)
    assert sw.speech_flags(_post("Текст поста") + "\n[[SPLIT]]\n[[УЗЕЛ]] мета", api_key="k") == []
    assert "t.me" not in seen["user"] and "[[УЗЕЛ]]" not in seen["user"]


def test_fix_speech_passes_flags_and_reports_when_not_saved(monkeypatch):
    seen = {}
    monkeypatch.setattr(sw, "_turn", lambda task, *a, **k: seen.setdefault("task", task) or "ответ модели")
    monkeypatch.setattr(sw, "_newest_draft_stamp", lambda: ("same", 1.0))
    monkeypatch.setattr(sw.verify, "latest_draft", lambda *a, **k: "старый драфт")
    monkeypatch.setattr(sw.config, "load_agent", lambda *a, **k: {})
    post, saved = sw.fix_speech(["«одна педаль» — образ — «станок»"], api_key="k")
    assert "«одна педаль»" in seen["task"] and "save_draft(kind='scope')" in seen["task"]
    assert saved is False and post == "старый драфт"   # правка не легла — панель скажет правду


def test_pipeline_checks_speech_before_the_final_recheck():
    src = inspect.getsource(rp)
    assert src.index("scope_writer.speech_flags(") < src.index("ФОРМА ФИНАЛА И СТРУКТУРА — ВЛАДЕЛЬЦУ")


# ── мелочи прогона 14.09 ────────────────────────────────────────────────────────────────────────

def test_usefulness_panel_keeps_the_whole_line():
    v = "ПОЛЬЗА: инвестор понимает механизм — почему «тормоза» в AI-индустрии разгоняют станок"
    assert tg.parse_usefulness(v).startswith("инвестор понимает механизм")


def test_gate_knows_the_quiet_splice():
    assert "ДАВНИЙ тезис" in tg._SYSTEM and "1+1 сплёл" in tg._SYSTEM


def test_manual_finale_is_taught_on_owner_finals():
    manual = (ct.config.ROOT / "memory" / "scope_manual.md").read_text(encoding="utf-8")
    fin = manual.split("## 4.5", 1)[1].split("## 5.", 1)[0]
    assert "гасить их будут новыми деньгами" in fin
    assert "**афоризм:**" not in fin and "**рефрейм образа:**" not in fin
