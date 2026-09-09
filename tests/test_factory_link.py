"""Опознание заводских постов Threads среди личной ленты.

Без сети: подменяем выгрузки на временные файлы. Проверяем ровно то, ради чего модуль написан —
что личное НЕ попадает в замер (иначе средние врут), что серия флагмана цепляется к одному ТГ-посту,
и что ручная пометка владельца переживает пересборку карты."""
import json

from core import factory_link as fl

# длина решает формат (порог завода 1500 знаков) — повторяем абзац, чтобы это был именно флагман
TG_FLAGSHIP = ("Заголовок про трансфер-агентов SEC\n\n" + "Комиссия предложила переписать правила "
               "реестра владельцев акций впервые за сорок лет, назвав блокчейн инструментом. " * 20)
TH_DERIVED = ("SEC впервые за сорок лет переписывает правила реестра владельцев акций - "
              "и называет блокчейн инструментом, под который их затачивают")
TH_PERSONAL = "Просто хочется денег"


def _data(tmp_path, monkeypatch, tg_rows, th_rows, formats=None):
    for name, rows in (("tg.json", tg_rows), ("th.json", th_rows), ("fmt.json", formats or {})):
        (tmp_path / name).write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(fl, "TG_POSTS", tmp_path / "tg.json")
    monkeypatch.setattr(fl, "THREADS_POSTS", tmp_path / "th.json")
    monkeypatch.setattr(fl, "TG_FORMATS", tmp_path / "fmt.json")
    monkeypatch.setattr(fl, "MAP_FILE", tmp_path / "map.json")
    monkeypatch.setattr(fl, "_known_ids", lambda: {})


def _today(offset_days: int = 0) -> str:
    from datetime import date, timedelta
    return (date.today() - timedelta(days=offset_days)).isoformat() + "T16:00:00"


def test_personal_post_is_not_counted_as_factory(tmp_path, monkeypatch):
    _data(tmp_path, monkeypatch,
          [{"id": 500, "date": _today(2), "text": TG_FLAGSHIP}],
          [{"id": "t1", "date": _today(2), "text": TH_DERIVED},
           {"id": "t2", "date": _today(2), "text": TH_PERSONAL}])
    r = fl.build(90)
    assert [p["id"] for p in r["factory"]] == ["t1"]          # переработка опознана
    assert [p["id"] for p in r["personal"]] == ["t2"]         # короткая личная реплика — мимо
    assert r["map"]["t1"]["tg_id"] == 500 and r["map"]["t1"]["kind"] == "flagship"


def test_series_of_threads_links_to_one_tg_post(tmp_path, monkeypatch):
    """Мини-флагман = 1-4 треда из ОДНОГО поста: все должны привязаться к нему, а не потеряться."""
    _data(tmp_path, monkeypatch,
          [{"id": 501, "date": _today(3), "text": TG_FLAGSHIP}],
          [{"id": "a", "date": _today(3), "text": TH_DERIVED},
           {"id": "b", "date": _today(2), "text": TH_DERIVED + " Правила реестра меняются"}])
    r = fl.build(90)
    assert {p["id"] for p in r["factory"]} == {"a", "b"}      # второй тред вышел на след. день — окно 1д
    assert {r["map"]["a"]["tg_id"], r["map"]["b"]["tg_id"]} == {501}


def test_manual_mark_survives_rebuild(tmp_path, monkeypatch):
    """Рука владельца сильнее алгоритма: помеченная связь не переписывается пересборкой."""
    _data(tmp_path, monkeypatch,
          [{"id": 502, "date": _today(1), "text": TG_FLAGSHIP}],
          [{"id": "z", "date": _today(1), "text": TH_PERSONAL}])
    fl.mark("z", 502, "scope")
    r = fl.build(90)
    assert r["map"]["z"] == {"tg_id": 502, "kind": "scope", "by": "рука"}
    assert [p["id"] for p in r["factory"]] == ["z"]


def test_service_tagged_tg_post_is_not_a_source(tmp_path, monkeypatch):
    """Разметка Аналитика отсеивает не-наш контент (личное/служебное) на стороне ТГ."""
    _data(tmp_path, monkeypatch,
          [{"id": 503, "date": _today(1), "text": TG_FLAGSHIP}],
          [{"id": "q", "date": _today(1), "text": TH_DERIVED}],
          formats={"503": "личный"})
    r = fl.build(90)
    assert r["factory"] == [] and [p["id"] for p in r["personal"]] == ["q"]
