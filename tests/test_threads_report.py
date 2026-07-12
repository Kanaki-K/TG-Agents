"""Тесты Threads-разбора для Аналитика (Фаза 2): build_report/find_posts на синтетике, без обращений к API."""
from connectors.threads import report


def _posts():
    # newest = 2026-07-12 → «сейчас»; посты ≤ 2026-06-28 зрелые (>14 дн); views≥150 годны для качества
    return [
        {"id": "1", "date": "2026-07-12", "text": "свежий пост про биткоин", "views": 500,
         "likes": 20, "reposts": 2, "people_replies": 1, "people_count": 1, "er": 2.0},
        {"id": "2", "date": "2026-06-01", "text": "крипта и рынок падают", "views": 800, "likes": 40,
         "reposts": 5, "people_replies": 6, "people_count": 4, "er": 3.2, "has_media": True},
        {"id": "3", "date": "2026-05-20", "text": "личное про путешествие в Рим", "views": 300,
         "likes": 10, "reposts": 0, "people_replies": 2, "people_count": 3, "er": 2.1},
        {"id": "4", "date": "2026-05-10", "text": "ссылка на статью https://example.com", "views": 200,
         "likes": 8, "reposts": 1, "people_replies": 1, "people_count": 2, "er": 1.5, "has_link": True},
        {"id": "5", "date": "2026-04-15", "text": "виральный пост про психологию силы", "views": 1000,
         "likes": 50, "reposts": 10, "people_replies": 8, "people_count": 6, "er": 4.0, "has_media": True},
        {"id": "6", "date": "2026-04-01", "text": "self-тред про осознанность", "views": 160, "likes": 5,
         "reposts": 0, "people_replies": 7, "people_count": 1, "self_replies": 5, "er": 1.2},
    ]


_TOPICS = {
    "2": {"title": "Крипта падает", "theme": "Новости рынка"},
    "3": {"title": "Поездка в Рим", "theme": "Личное"},
    "5": {"title": "Психология силы", "theme": "Психология"},
    "6": {"title": "Осознанность", "theme": "Личное"},
    "4": {"title": "Полезная статья", "theme": "Обучение"},
}


def test_build_report_renders_sections():
    out = report.build_report(_posts(), _TOPICS)
    assert isinstance(out, str)
    for section in ("THREADS", "[КОРПУС]", "[КАЧЕСТВО", "[ОХВАТ", "[ТЕМЫ]", "[ДУШИТЕЛИ ОХВАТА]"):
        assert section in out, f"нет секции {section}"


def test_build_report_empty_is_friendly():
    out = report.build_report([], {})
    assert "Нет данных Threads" in out          # дружелюбно, не трейсбек


def test_find_posts_matches_by_text_and_title():
    out = report.find_posts("крипт", posts=_posts(), topics=_TOPICS)
    assert "крипта и рынок падают" in out or "Крипта падает" in out
    # найденное отсортировано, есть строка с просмотрами
    assert "просм" in out


def test_find_posts_by_title_only():
    out = report.find_posts("Рим", posts=_posts(), topics=_TOPICS)
    assert "Рим" in out and "не найдено" not in out


def test_find_posts_no_hits_and_empty_query():
    assert "не найдено" in report.find_posts("оченьредкоеслово", posts=_posts(), topics=_TOPICS)
    assert "Пустой запрос" in report.find_posts("", posts=_posts(), topics=_TOPICS)
