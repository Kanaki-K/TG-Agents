"""Фикс twikit под изменения фронта X (18.03.2026).

X сменил формат ссылки на скрипт ondemand.s в HTML главной страницы (теперь имя файла
ищется в два шага: числовой индекс чанка → хэш), и регулярки в
twikit/x_client_transaction/transaction.py перестали совпадать. Любой вызов падает с
«Couldn't get KEY_BYTE indices» — библиотека нерабочая у всех, пока фикс не вольют в релиз.

Здесь переносим исправление из апстрим-PR d60/twikit#411 как monkeypatch: чиним
ОФИЦИАЛЬНЫЙ twikit на лету, не модифицируя site-packages и не подключая сторонний форк
(чтобы не тащить чужой код к секретам в .env). Тело get_indices скопировано из PR дословно.

Патч само-отключается, когда апстрим догонит (в нём появится ON_DEMAND_HASH_PATTERN).
Когда twikit выпустит релиз с фиксом — этот файл и вызов apply() в read.py можно удалить.
"""
from __future__ import annotations

import re

_ON_DEMAND_FILE_REGEX = re.compile(
    r',(\d+):["\']ondemand\.s["\']', flags=(re.VERBOSE | re.MULTILINE))
_ON_DEMAND_HASH_PATTERN = r',{}:"([0-9a-f]+)"'
_INDICES_REGEX = re.compile(r'\[(\d+)\],\s*16')


async def _get_indices(self, home_page_response, session, headers):
    key_byte_indices = []
    response = self.validate_response(
        home_page_response) or self.home_page_response
    on_demand_match = _ON_DEMAND_FILE_REGEX.search(str(response))
    if on_demand_match:
        chunk_index = on_demand_match.group(1)
        hash_match = re.search(
            _ON_DEMAND_HASH_PATTERN.format(chunk_index), str(response))
        if hash_match:
            file_hash = hash_match.group(1)
            on_demand_file_url = f"https://abs.twimg.com/responsive-web/client-web/ondemand.s.{file_hash}a.js"
            on_demand_file_response = await session.request(method="GET", url=on_demand_file_url, headers=headers)
            for item in _INDICES_REGEX.finditer(on_demand_file_response.text):
                key_byte_indices.append(item.group(1))
    if not key_byte_indices:
        raise Exception("Couldn't get KEY_BYTE indices")
    key_byte_indices = list(map(int, key_byte_indices))
    return key_byte_indices[0], key_byte_indices[1:]


# Поля профиля, которые User.__init__ берёт жёстко (legacy['...']) — текущий X часть
# из них не отдаёт. Подставляем дефолты ДО разбора, чтобы не было KeyError ни на каком.
_USER_LEGACY_DEFAULTS = {
    "created_at": "", "name": "", "screen_name": "", "profile_image_url_https": "",
    "location": "", "description": "", "pinned_tweet_ids_str": [],
    "verified": False, "possibly_sensitive": False, "can_dm": False,
    "can_media_tag": False, "want_retweets": False, "default_profile": False,
    "default_profile_image": False, "has_custom_timelines": False,
    "followers_count": 0, "fast_followers_count": 0, "normal_followers_count": 0,
    "friends_count": 0, "favourites_count": 0, "listed_count": 0, "media_count": 0,
    "statuses_count": 0, "is_translator": False, "translator_type": "none",
    "withheld_in_countries": [],
}

# Поля твита, которые читаются жёстко (через @property: full_text, счётчики и т.п.).
_TWEET_LEGACY_DEFAULTS = {
    "created_at": "", "full_text": "", "lang": "", "is_quote_status": False,
    "reply_count": 0, "favorite_count": 0, "favorited": False, "retweet_count": 0,
}


def _patch_user() -> None:
    """User.__init__ жёстко читает ~25 полей legacy; текущий X отдаёт не все
    (видели KeyError 'urls', 'withheld_in_countries'). Гарантируем дефолты до разбора."""
    try:
        from twikit import user as _u
    except Exception:
        return
    orig_init = _u.User.__init__
    if getattr(orig_init, "_kanaki_patched", False):
        return

    def _safe_init(self, client, data):
        if isinstance(data, dict):
            data.setdefault("rest_id", "")
            data.setdefault("is_blue_verified", False)
            legacy = data.setdefault("legacy", {})
            for k, v in _USER_LEGACY_DEFAULTS.items():
                legacy.setdefault(k, v)
            ent = legacy.setdefault("entities", {})
            ent.setdefault("description", {}).setdefault("urls", [])
            ent.setdefault("url", {}).setdefault("urls", [])
        orig_init(self, client, data)

    _safe_init._kanaki_patched = True
    _u.User.__init__ = _safe_init


def _patch_tweet() -> None:
    """Tweet читает поля legacy жёстко через @property (full_text, счётчики).
    Гарантируем их наличие, заполнив legacy дефолтами в __init__."""
    try:
        from twikit import tweet as _tw
    except Exception:
        return
    orig_init = _tw.Tweet.__init__
    if getattr(orig_init, "_kanaki_patched", False):
        return

    def _safe_init(self, client, data, user=None):
        if isinstance(data, dict):
            data.setdefault("rest_id", "")
            legacy = data.setdefault("legacy", {})
            for k, v in _TWEET_LEGACY_DEFAULTS.items():
                legacy.setdefault(k, v)
        orig_init(self, client, data, user)

    _safe_init._kanaki_patched = True
    _tw.Tweet.__init__ = _safe_init


def apply() -> None:
    """Пропатчить сломанный апстримом twikit (PR #411 + защита разбора профиля). Иначе — no-op."""
    try:
        from twikit.x_client_transaction import transaction as _t
    except Exception:
        return  # twikit не установлен или иная структура — тихо выходим
    if not hasattr(_t, "ON_DEMAND_HASH_PATTERN"):  # апстрим ещё не пофикшен → чиним
        _t.ON_DEMAND_FILE_REGEX = _ON_DEMAND_FILE_REGEX
        _t.ON_DEMAND_HASH_PATTERN = _ON_DEMAND_HASH_PATTERN
        _t.INDICES_REGEX = _INDICES_REGEX
        _t.ClientTransaction.get_indices = _get_indices
    _patch_user()
    _patch_tweet()
