"""Тесты SSRF-защиты fetch_page (core web_sources/feeds). Только IP-литералы/схемы — без сети/DNS."""
from connectors.web_sources import feeds


def test_ip_blocked_private_and_local():
    for ip in ["127.0.0.1", "10.0.0.1", "192.168.1.1", "172.16.0.1",
               "169.254.169.254", "::1", "0.0.0.0", "не-айпи"]:
        assert feeds._ip_is_blocked(ip) is True, ip


def test_ip_allowed_public():
    for ip in ["8.8.8.8", "1.1.1.1", "93.184.216.34"]:
        assert feeds._ip_is_blocked(ip) is False, ip


def test_url_blocked_reason_scheme():
    assert feeds._url_blocked_reason("ftp://example.com") is not None
    assert feeds._url_blocked_reason("file:///etc/passwd") is not None


def test_url_blocked_reason_private_targets():
    # IP-литералы: getaddrinfo не ходит в DNS, проверка чистая
    assert feeds._url_blocked_reason("http://127.0.0.1/admin") is not None
    assert feeds._url_blocked_reason("http://169.254.169.254/latest/meta-data/") is not None
    assert feeds._url_blocked_reason("http://[::1]:8080/") is not None


def test_url_allowed_public_ip():
    # публичный IP-литерал — резолва нет, должен пройти (None = разрешено)
    assert feeds._url_blocked_reason("http://8.8.8.8/") is None
    assert feeds._url_blocked_reason("https://1.1.1.1/") is None
