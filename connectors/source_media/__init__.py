"""Медиа первоисточника — «рука» для обложки поста из штатной картинки новости.

Тянем со страницы, на которой построен пост, все разумные кадры — og:image/twitter:image (шапка)
и картинки из тела статьи (график/схема/скрин/фото) — и скачиваем их.
НЕ генерация (это не GPT-обложка флагмана) — берём картинку, которую к материалу
прикрепил сам источник. Ленивая тяга: вызывается ТОЛЬКО для готового поста, не для всех
кандидатов брифа (см. scope_writer). SSRF-защита переиспользуется из web_sources.feeds.

Кадры со страниц повода — не единственный маршрут. Второй, `subject_media`, ИЩЕТ кадр по самому
объекту повода (полотно бренда / здание / человек / лого) — он и вытаскивает обложку, когда статьи
не дали ничего или дали один ИИ-сток. Тоже не генерация: всё скачано из открытых источников как есть.
"""
from connectors.source_media.fetch import (article_images, download, fetch_source_image,
                                           fetch_source_images, frame_fingerprint, looks_same,
                                           og_image_url)
from connectors.source_media.subject_media import MIN_LOGO_SIDE, subject_image_urls

__all__ = ["article_images", "download", "fetch_source_image", "fetch_source_images",
           "frame_fingerprint", "looks_same", "og_image_url", "subject_image_urls",
           "MIN_LOGO_SIDE"]
