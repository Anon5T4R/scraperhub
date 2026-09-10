"""Registro de scrapers e deteccao automatica por URL."""
from __future__ import annotations

from .base import Scraper, ScraperError
from .mangafire import MangaFireScraper
from .video import VideoScraper

REGISTRY: list[Scraper] = [
    MangaFireScraper(),
    VideoScraper(),
]


def normalize_url(url: str) -> str:
    """Normaliza a URL: trim + prefixo https:// quando o usuario omitiu."""
    url = url.strip()
    if url and "://" not in url:
        url = "https://" + url
    return url


def detect(url: str) -> Scraper | None:
    """Retorna o primeiro scraper que aceita a URL, ou None."""
    url = normalize_url(url)
    for scraper in REGISTRY:
        if scraper.match(url):
            return scraper
    return None


def get_scraper(scraper_id: str) -> Scraper | None:
    """Retorna o scraper com o id informado, ou None."""
    for scraper in REGISTRY:
        if scraper.id == scraper_id:
            return scraper
    return None


__all__ = ["REGISTRY", "Scraper", "ScraperError", "detect", "get_scraper"]
