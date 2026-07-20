"""Гейт польза-эдж (core/usefulness) — решающий слой: блокировать пересказ, пропускать пользу,
и НЕ ронять публикацию на сбое самого гейта (вторичная сеть, фейл-ОТКРЫТО). Судейское суждение
модели тут не проверяем (это живой прогон) — проверяем ПЛУМБИНГ и решение по вердикту."""
from core import usefulness


def test_blocks_on_pereskaz():
    assert usefulness.blocks("разбор по признакам...\nГЕЙТ: ПЕРЕСКАЗ") is True


def test_does_not_block_on_polza():
    assert usefulness.blocks("ВЫВОД ДЛЯ ЧИТАТЕЛЯ: ...\nГЕЙТ: ПОЛЬЗА") is False


def test_failopen_when_no_verdict_line():
    # нет строки ГЕЙТ (сбой/пустота вердикта) → НЕ блокируем: гейт вторичен после 2FA, фейл-ОТКРЫТО
    assert usefulness.blocks("") is False
    assert usefulness.blocks(None) is False
    assert usefulness.blocks("(гейт польза-эдж не удался: timeout)") is False


def test_empty_post_blocks_without_calling_model(monkeypatch):
    # пустой пост → вердикт ПЕРЕСКАЗ БЕЗ вызова модели (не жжём токены на пустышку)
    calls = []
    monkeypatch.setattr(usefulness.llm, "reply", lambda *a, **k: calls.append(1))
    v = usefulness.judge("")
    assert usefulness.blocks(v) is True
    assert calls == []                      # модель не звалась


def test_judge_returns_model_verdict(monkeypatch):
    monkeypatch.setattr(usefulness.llm, "reply", lambda *a, **k: ("разбор\nГЕЙТ: ПОЛЬЗА", []))
    v = usefulness.judge("Реальный пост с выводом для читателя", "бриф", model="m")
    assert "ГЕЙТ: ПОЛЬЗА" in v
    assert usefulness.blocks(v) is False


def test_judge_sees_only_pre_split_text(monkeypatch):
    # мета после [[SPLIT]] (заметка владельцу) НЕ должна попадать судье — только сам пост
    seen = {}

    def fake(mdl, system, hist, user, tools, disp, key, thinking, **k):
        seen["user"] = user
        return ("ГЕЙТ: ПЕРЕСКАЗ", [])

    monkeypatch.setattr(usefulness.llm, "reply", fake)
    usefulness.judge("ВИДИМЫЙ пост\n[[SPLIT]]\nСЕКРЕТНАЯ мета", model="m")
    assert "ВИДИМЫЙ" in seen["user"] and "СЕКРЕТНАЯ" not in seen["user"]


def test_judge_failopen_on_model_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("api down")

    monkeypatch.setattr(usefulness.llm, "reply", boom)
    v = usefulness.judge("пост", model="m")
    assert usefulness.blocks(v) is False    # сбой гейта НЕ блокирует публикацию (фейл-открыто)
