"""Медиа первоисточника — «рука» для обложки поста из штатной картинки новости.

Тянем og:image/twitter:image со страницы, на которой построен пост, и скачиваем её.
НЕ генерация (это не GPT-обложка флагмана) — берём картинку, которую к материалу
прикрепил сам источник. Ленивая тяга: вызывается ТОЛЬКО для готового поста, не для всех
кандидатов брифа (см. scope_writer). SSRF-защита переиспользуется из web_sources.feeds.
"""
from connectors.source_media.fetch import download, fetch_source_image, og_image_url

__all__ = ["download", "fetch_source_image", "og_image_url"]
