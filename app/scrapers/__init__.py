"""Registro de scrapers e deteccao automatica por URL."""
from __future__ import annotations

from urllib.parse import urlparse

from .base import Scraper, ScraperError
from .animestream import AnimeStreamScraper
from .ebook import EbookScraper
from .enanime import EnAnimeScraper
from .filehost import FileHostScraper
from .gallery import GalleryScraper
from .mangafire import MangaFireScraper
from .mirror import MirrorScraper
from .tsundoku import TsundokuScraper
from .video import VideoScraper
from .wpmanga import WpMangaScraper

# Ordem CRITICA: scrapers especificos antes dos genericos; `video` e o
# fallback final (aceita qualquer URL http). `mirror` so entra via force.
REGISTRY: list[Scraper] = [
    MangaFireScraper(),
    TsundokuScraper(),
    WpMangaScraper(),
    GalleryScraper(),
    EbookScraper(),
    FileHostScraper(),
    AnimeStreamScraper(),
    EnAnimeScraper(),
    MirrorScraper(),
    VideoScraper(),
]


def normalize_url(url: str) -> str:
    """Normaliza a URL: trim + prefixo https:// e valida scheme/hostname.

    Levanta ValueError quando a URL nao tem scheme http/https ou um
    hostname valido (vazio, com espacos ou sem nenhum caractere alfanumerico).
    """
    url = url.strip()
    if url and "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if (
        parsed.scheme not in ("http", "https")
        or not host
        or " " in host
        or not any(c.isalnum() for c in host)
    ):
        raise ValueError(f"URL inválida: {url}")
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
