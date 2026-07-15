"""Тесты защиты аккаунта Threads (_guard + врезка в _api). Сеть НЕ трогаем — urlopen подменён.

Почему эти тесты важнее обычных: они охраняют не фичу, а аккаунт. 14.07.2026 через коннектор
прошла массовая выгрузка (5000 ответов, несколько полных проходов за 40 минут, без пауз) →
аккаунт получил проверку. Здесь закреплено ровно то, что тогда отсутствовало.

Главный тест — test_default_state_blocks_network: он ловит регресс «кто-то снял защиту».
"""
import json
import time

import pytest

from connectors.threads import _api, _guard


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Уводим все файлы состояния во временную папку — тесты не трогают живой data/."""
    monkeypatch.setattr(_guard, "UNLOCK_FILE", tmp_path / "threads_unlocked")
    monkeypatch.setattr(_guard, "COOLDOWN_FILE", tmp_path / "threads_cooldown")
    monkeypatch.setattr(_guard, "LOG_FILE", tmp_path / "threads_api_log.jsonl")
    # Счётчики модуля глобальные — сбрасываем, иначе тесты текут друг в друга.
    monkeypatch.setattr(_guard, "_run_count", 0)
    monkeypatch.setattr(_guard, "_last_call_at", 0.0)
    monkeypatch.setattr(_guard, "_next_breather", 10_000)  # «пауза на подумать» не мешает тестам
    # Темп не выдерживаем по-настоящему: тест не должен спать 6 секунд.
    monkeypatch.setattr(_guard.time, "sleep", lambda s: None)
    return tmp_path


class _FakeResponse:
    def __init__(self, body: bytes, headers: dict | None = None):
        self._body = body
        self.headers = headers if headers is not None else {}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def spy(monkeypatch):
    """Подмена urlopen: ловим запросы, наружу ничего не уходит."""
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(req)
        return _FakeResponse(json.dumps({"id": "42", "username": "kanaki.crypto"}).encode())

    monkeypatch.setattr(_api.urllib.request, "urlopen", fake_urlopen)
    return calls


# --- Состояние по умолчанию: закрыто ------------------------------------------------

def test_default_state_blocks_network(sandbox, spy):
    """БЕЗ файла-разблокировки запрос не уходит ВООБЩЕ. Это состояние по умолчанию.

    Если этот тест упал — значит защиту сняли или инвертировали. Не «чинить» его правкой
    ожиданий: сначала понять, почему сеть открылась сама.
    """
    with pytest.raises(_guard.ThreadsBlocked):
        _api.get("me", {"fields": "id"}, token="TOK")
    assert spy == [], "запрос ушёл в сеть при закрытом состоянии"


def test_unlock_opens_network(sandbox, spy):
    _guard.unlock("тест")
    _api.get("me", {"fields": "id"}, token="TOK")
    assert len(spy) == 1


def test_unlock_requires_reason(sandbox):
    """Открыть «просто так» нельзя — причина потом читается глазами."""
    with pytest.raises(ValueError):
        _guard.unlock("   ")


def test_lock_closes_again(sandbox, spy):
    _guard.unlock("тест")
    _guard.lock()
    with pytest.raises(_guard.ThreadsBlocked):
        _api.get("me", {"fields": "id"}, token="TOK")
    assert spy == []


# --- Предохранитель: троттлинг гасит прогон ------------------------------------------

def test_429_trips_cooldown_and_stops_run(sandbox, monkeypatch):
    """429 → не retry, а стоп и остывание. Повтор в ответ на «ты частый» — то самое поведение,
    из-за которого 14.07 три захода слились в один сплошной след."""
    _guard.unlock("тест")

    def boom(req, timeout=None):
        raise _api.urllib.error.HTTPError(
            req.full_url, 429, "Too Many Requests", {},
            _io_bytes(json.dumps({"error": {"message": "limit", "code": 4}}).encode()),
        )

    monkeypatch.setattr(_api.urllib.request, "urlopen", boom)
    with pytest.raises(_guard.ThreadsBlocked):
        _api.get("me", {"fields": "id"}, token="TOK")
    assert _guard.COOLDOWN_FILE.exists(), "предохранитель не записал остывание"
    # Следующий запрос не должен даже пытаться.
    assert "предохранитель" in _guard.frozen_reason()


def test_cooldown_expires(sandbox):
    _guard.unlock("тест")
    _guard.COOLDOWN_FILE.write_text(str(time.time() - 1), encoding="utf-8")
    assert _guard.frozen_reason() == "", "просроченное остывание должно сниматься само"
    assert not _guard.COOLDOWN_FILE.exists()


def test_meta_throttle_code_without_429(sandbox, monkeypatch):
    """Meta умеет отдавать лимит и не-429 статусом — ловим по коду в теле."""
    _guard.unlock("тест")

    def boom(req, timeout=None):
        raise _api.urllib.error.HTTPError(
            req.full_url, 400, "Bad Request", {},
            _io_bytes(json.dumps({"error": {"message": "rate", "code": 613}}).encode()),
        )

    monkeypatch.setattr(_api.urllib.request, "urlopen", boom)
    with pytest.raises(_guard.ThreadsBlocked):
        _api.get("me", {"fields": "id"}, token="TOK")
    assert _guard.COOLDOWN_FILE.exists()


def test_ordinary_error_does_not_trip(sandbox, monkeypatch):
    """Обычная ошибка (не троттлинг) не должна гасить всё на 6 часов."""
    _guard.unlock("тест")

    def boom(req, timeout=None):
        raise _api.urllib.error.HTTPError(
            req.full_url, 400, "Bad Request", {},
            _io_bytes(json.dumps({"error": {"message": "bad field", "code": 100}}).encode()),
        )

    monkeypatch.setattr(_api.urllib.request, "urlopen", boom)
    with pytest.raises(_api.ThreadsError):
        _api.get("me", {"fields": "id"}, token="TOK")
    assert not _guard.COOLDOWN_FILE.exists()


# --- Бюджеты -------------------------------------------------------------------------

def test_run_budget_stops_run(sandbox, spy, monkeypatch):
    _guard.unlock("тест")
    monkeypatch.setattr(_guard, "RUN_BUDGET", 3)
    for _ in range(3):
        _api.get("me", {"fields": "id"}, token="TOK")
    with pytest.raises(_guard.ThreadsBlocked, match="Бюджет прогона"):
        _api.get("me", {"fields": "id"}, token="TOK")
    assert len(spy) == 3, "бюджет пропустил лишний запрос"


def test_day_budget_counts_journal(sandbox, spy, monkeypatch):
    """Дневной счётчик переживает перезапуск процесса — читается из журнала, не из памяти."""
    _guard.unlock("тест")
    monkeypatch.setattr(_guard, "DAY_BUDGET", 2)
    _api.get("me", {"fields": "id"}, token="TOK")
    _api.get("me", {"fields": "id"}, token="TOK")
    monkeypatch.setattr(_guard, "_run_count", 0)  # как будто новый процесс
    with pytest.raises(_guard.ThreadsBlocked, match="Дневной бюджет"):
        _api.get("me", {"fields": "id"}, token="TOK")


def test_old_journal_entries_do_not_count(sandbox, monkeypatch):
    """Сутки скользящие: вчерашние запросы не должны блокировать сегодня."""
    _guard.unlock("тест")
    _guard.LOG_FILE.write_text(
        "\n".join(json.dumps({"at": time.time() - 90_000}) for _ in range(50)) + "\n",
        encoding="utf-8",
    )
    assert _guard._calls_last_24h() == 0


# --- Темп ----------------------------------------------------------------------------

def test_pause_between_calls(sandbox, spy, monkeypatch):
    """Между запросами обязана быть пауза, и не ровная — ровная сама по себе машинная подпись."""
    slept = []
    monkeypatch.setattr(_guard.time, "sleep", lambda s: slept.append(s))
    _guard.unlock("тест")
    for _ in range(4):
        _api.get("me", {"fields": "id"}, token="TOK")
    assert len(slept) >= 3, "паузы между запросами исчезли"
    assert all(s >= 1.0 for s in slept), f"слишком короткие паузы: {slept}"
    assert len(set(slept)) > 1, "паузы одинаковые — нет разброса"


# --- Гигиена: токен и журнал ---------------------------------------------------------

def test_token_goes_in_header_not_url(sandbox, spy):
    """Токен в query утекал бы в логи прокси и access-логи Meta."""
    _guard.unlock("тест")
    _api.get("me", {"fields": "id"}, token="SECRET123")
    req = spy[0]
    assert "SECRET123" not in req.full_url, "токен утёк в URL"
    assert req.get_header("Authorization") == "Bearer SECRET123"


def test_user_agent_is_not_python_urllib(sandbox, spy):
    _guard.unlock("тест")
    _api.get("me", {"fields": "id"}, token="TOK")
    ua = spy[0].get_header("User-agent") or ""
    assert "urllib" not in ua.lower() and "python" not in ua.lower(), f"машинный UA: {ua}"


def test_journal_records_call_without_token(sandbox, spy):
    _guard.unlock("тест")
    _api.get("me", {"fields": "id"}, token="SECRET123")
    lines = _guard.LOG_FILE.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["status"] == 200
    assert row["endpoint"].endswith("/me")
    assert "SECRET123" not in lines[0], "токен попал в журнал"


def test_journal_records_failures_too(sandbox, monkeypatch):
    """Ошибки тоже в журнал — иначе картина сбора снова будет неполной."""
    _guard.unlock("тест")

    def boom(req, timeout=None):
        raise _api.urllib.error.URLError("нет сети")

    monkeypatch.setattr(_api.urllib.request, "urlopen", boom)
    with pytest.raises(_api.ThreadsError):
        _api.get("me", {"fields": "id"}, token="TOK")
    row = json.loads(_guard.LOG_FILE.read_text(encoding="utf-8").strip())
    assert row["status"] is None and row["error"]


# --- Квота глазами Meta (x-app-usage) -----------------------------------------------
# Реальная квота Threads API = 4800 * показы за 24ч, минимум показов 10 → пол квоты 48 000
# запросов в сутки. Наши бюджеты (120/прогон, 300/сутки) на порядки ниже — они про аккуратность,
# а не про лимит Meta. Но проценты из заголовка — единственный честный сигнал, и мы их слушаем.

def test_usage_parsed_from_headers(sandbox, monkeypatch):
    _guard.unlock("тест")

    usage = {"x-app-usage": json.dumps({"call_count": 3, "total_cputime": 1, "total_time": 2})}
    monkeypatch.setattr(_api.urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeResponse(b'{"id": "42"}', usage))
    _api.get("me", {"fields": "id"}, token="TOK")
    row = json.loads(_guard.LOG_FILE.read_text(encoding="utf-8").strip())
    assert row["usage"]["x-app-usage"]["call_count"] == 3, "расход квоты не попал в журнал"


def test_high_usage_stops_run_before_limit(sandbox, monkeypatch):
    """На 80% тормозим САМИ: 100% — это уже отказ и отметка в системе Meta."""
    _guard.unlock("тест")

    hot = {"x-app-usage": json.dumps({"call_count": 85, "total_cputime": 10, "total_time": 12})}
    monkeypatch.setattr(_api.urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeResponse(b'{"id": "42"}', hot))
    with pytest.raises(_guard.ThreadsBlocked, match="Квота Meta"):
        _api.get("me", {"fields": "id"}, token="TOK")
    assert _guard.COOLDOWN_FILE.exists()


def test_peak_percent_takes_worst_metric():
    """Упрёмся в ЛЮБОЙ из лимитов — тормознут всё, поэтому смотрим на худший."""
    usage = {"x-app-usage": {"call_count": 5, "total_cputime": 91, "total_time": 3}}
    assert _guard._peak_percent(usage) == 91


def test_missing_usage_headers_are_harmless(sandbox, monkeypatch):
    """Заголовков может не быть вовсе — это не повод падать или блокировать."""
    _guard.unlock("тест")

    class _NoHeaders:
        def read(self):
            return json.dumps({"id": "42"}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(_api.urllib.request, "urlopen", lambda req, timeout=None: _NoHeaders())
    assert _api.get("me", {"fields": "id"}, token="TOK") == {"id": "42"}


def _io_bytes(b: bytes):
    """HTTPError ждёт файло-подобный объект в fp."""
    import io

    return io.BytesIO(b)
