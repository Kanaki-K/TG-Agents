"""ГЕЙТ ВЫХОДА scope КОДОМ (creator_tools.scope_meta_defects + scope_writer.fix_meta).

ЗАЧЕМ ЭТИ ТЕСТЫ. §7.4 требует в мете строку [[УЗЕЛ]], §7.45 (решение владельца 10.09.2026) — строку
[[ВЫХОД]]: «что читатель сможет сделать или подумать завтра иначе». Оба требования жили ТОЛЬКО
просьбой в промпте. Прогон 12.09.2026 показал цену: писатель не выдал ни одной строки меты (в драфте
нет даже [[SPLIT]]), пайплайн опубликовал, владелец забраковал пост — «пользы 0, реально после
прочтения не ясно ни что делать, ни как прочитанное использовать». Гейт, придуманный ровно против
этого, не сработал, потому что его никто не проверял.
Запуск: python -m pytest tests/test_scope_exit_gate.py"""
from __future__ import annotations

from core import creator_tools as ct

BODY = ("**⚡️ Заголовок поста один**\n\nЛид с датой и цифрой\n\n"
        "Механика на пальцах\n\nФинал, который стоит сам\n\n🖥 Канал | 📱 Notion")


def _meta(node: str = "", exit_: str = "") -> str:
    m = "\n[[SPLIT]]\n"
    if node:
        m += f"[[УЗЕЛ]] {node}\n"
    if exit_:
        m += f"[[ВЫХОД]] {exit_}\n"
    return BODY + m


GOOD_NODE = "личность в цифре стала товаром, который можно одолжить"
GOOD_EXIT = "проверь, где лежат твои доступы, и не покупай их с рук"


def test_no_meta_at_all_is_the_12_09_case():
    """Дословный случай прогона 12.09: меты нет вовсе, и код обязан это увидеть."""
    d = ct.scope_meta_defects(BODY)
    assert d and "меты нет вовсе" in d[0]


def test_full_meta_passes():
    assert ct.scope_meta_defects(_meta(GOOD_NODE, GOOD_EXIT)) == []


def test_missing_node_and_missing_exit_are_named_separately():
    assert any("[[УЗЕЛ]]" in x for x in ct.scope_meta_defects(_meta(exit_=GOOD_EXIT)))
    assert any("[[ВЫХОД]]" in x for x in ct.scope_meta_defects(_meta(node=GOOD_NODE)))


def test_knowledge_verbs_are_not_an_exit():
    """«Теперь он знает про X» — формулировка владельца из §7.45: иллюзия знания вместо знания."""
    for bad in ("читатель узнает про новый класс атак и поймёт механику",
                "станет понятно, как устроена кража ключей у моделей",
                "инвестор осознает масштаб проблемы с доступами"):
        d = ct.scope_meta_defects(_meta(GOOD_NODE, bad))
        assert d and "иллюзия знания" in d[0], bad


def test_label_instead_of_action_is_rejected():
    # «будет в курсе» — ярлык длиной в два слова, а не действие читателя
    assert ct.scope_meta_defects(_meta(GOOD_NODE, "будет в курсе"))


def test_honest_no_exit_is_accepted_as_an_answer():
    """Честное «выхода нет, пост даёт понимание» — это ОТВЕТ (так велит §7.45: скажи владельцу прямо,
    а не выдавай понимание за защиту). Код не должен гонять круги против честного ответа."""
    assert ct.scope_meta_defects(
        _meta(GOOD_NODE, "поста-выхода нет: даёт понимание, не защиту — решай сам")) == []


def test_fix_meta_exists_and_is_cheap_to_call():
    # прицельный круг вызывается ТОЛЬКО при дефекте меты; подпись фиксируем, чтобы пайплайн не разъехался
    from core import scope_writer as sw
    assert callable(sw.fix_meta)
    assert "[[ВЫХОД]]" in sw.META_FIX and "иллюзия знания" in sw.META_FIX
    assert "read_draft" in sw.META_FIX and "save_draft" in sw.META_FIX   # правит через сохранение драфта
