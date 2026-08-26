"""Медиа первоисточника — «рука» для обложки поста из штатной картинки новости.

Тянем со страницы, на которой построен пост, все разумные кадры — og:image/twitter:image (шапка)
и картинки из тела статьи (график/схема/скрин/фото) — и скачиваем их.
НЕ генерация (это не GPT-обложка флагмана) — берём картинку, которую к материалу
прикрепил сам источник. Ленивая тяга: вызывается ТОЛЬКО для готового поста, не для всех
кандидатов брифа (см. scope_writer). SSRF-защита переиспользуется из web_sources.feeds.
"""
from connectors.source_media.fetch import (article_images, download, fetch_source_image,
                                           fetch_source_images, og_image_url)

__all__ = ["article_images", "download", "fetch_source_image", "fetch_source_images", "og_image_url"]
