"""Scraper de galerias de imagens usando gallery-dl (API Python).

O gallery-dl cobre centenas de sites (imgur, pixiv, reddit, boorus, etc).
Aqui ele e usado como biblioteca: `extractor.find` acha o extrator e o
`job.DataJob` percorre a galeria. Limitacao conhecida: mensagens do tipo
`Message.Queue` (sub-galerias/albuns encadeados) sao ignoradas; tratamos
a URL informada como uma galeria unica.
"""
from __future__ import annotations

import re
import time
from urllib.parse import urlparse

import httpx

from .base import DOWNLOADS_DIR, ProgressCb, Scraper, ScraperError
from .mangafire_parse import image_extension, sanitize

GALLERY_HOSTS = (
    r"imgur\.com",
    r"pinterest\.",
    r"pin\.it",
    r"reddit\.com/(?:r|user)/",
    r"danbooru\.donmai\.us",
    r"safebooru\.org",
    r"gelbooru\.com",
    r"yande\.re",
    r"konachan\.com",
    r"zerochan\.net",
    r"pixiv\.net",
    r"artstation\.com",
    r"tapas\.io",
    r"webtoons\.com",
    r"(?:x|twitter)\.com/",
    r"bsky\.app",
)
GALLERY_HOST_RE = re.compile("|".join(GALLERY_HOSTS), re.IGNORECASE)
TITLE_KEYS = ("title", "series", "category")
REQUEST_GAP_S = 0.2
HEADER_DROP = frozenset({"accept-encoding", "content-length", "host", "connection"})


class GalleryScraper(Scraper):
    """Galerias de imagens via gallery-dl (imgur, pixiv, reddit, boorus...)."""

    id = "gallery"
    label = "Galeria (gallery-dl)"
    kind = "image"

    def match(self, url: str) -> bool:
        return bool(GALLERY_HOST_RE.search(url))

    def get_info(self, url: str) -> dict:
        from gallery_dl import extractor, job
        from gallery_dl.extractor.message import Message

        if extractor.find(url) is None:
            raise ScraperError("URL nao reconhecida pelo gallery-dl.")
        data_job = job.DataJob(url, file=None)
        data_job.run()
        for msg in data_job.data:
            if len(msg) == 2 and msg[0] == -1:
                detail = msg[1].get("message") or msg[1].get("error") or "erro desconhecido"
                raise ScraperError(f"Falha ao analisar a galeria: {detail}")
        images = [msg for msg in data_job.data if len(msg) == 3 and msg[0] == Message.Url]
        return {
            "title": self._title(data_job.data, url),
            "cover": None,
            "items": [{"id": "1", "label": f"{len(images)} imagens"}],
        }

    def download(
        self,
        url: str,
        item_ids: list[str],
        progress_cb: ProgressCb,
        options: dict | None = None,
    ) -> None:
        from gallery_dl import extractor
        from gallery_dl.extractor.message import Message

        extr = extractor.find(url)
        if extr is None:
            raise ScraperError("URL nao reconhecida pelo gallery-dl.")
        try:
            messages = list(extr)
        except Exception as exc:  # erro de rede/extrator do gallery-dl
            raise ScraperError(f"Falha ao extrair a galeria: {exc}") from exc
        images = [msg for msg in messages if len(msg) == 3 and msg[0] == Message.Url]
        if not images:
            raise ScraperError("Nenhuma imagem encontrada nesta galeria.")

        category = sanitize(getattr(extr, "category", "") or "gallery")
        folder = DOWNLOADS_DIR / category / self._title(messages, url)
        headers = self._headers(extr, url)
        total = len(images)
        with httpx.Client(headers=headers, follow_redirects=True, timeout=60) as client:
            for index, (_, image_url, meta) in enumerate(images, start=1):
                data = self._get(client, image_url, url)
                extension = self._extension(image_url, meta, data)
                folder.mkdir(parents=True, exist_ok=True)
                (folder / f"{index:03d}{extension}").write_bytes(data)
                progress_cb(int(index * 100 / total), f"img {index}/{total}")
                time.sleep(REQUEST_GAP_S)
        progress_cb(100, "Concluido")

    # -- helpers -------------------------------------------------------

    @staticmethod
    def _title(messages: list, url: str) -> str:
        for msg in messages:
            meta = msg[1] if len(msg) == 2 else (msg[2] if len(msg) == 3 else None)
            if meta:
                value = GalleryScraper._first(meta)
                if value:
                    return sanitize(value)
        return sanitize(urlparse(url).netloc or "galeria")

    @staticmethod
    def _first(meta: dict) -> str | None:
        for key in TITLE_KEYS:
            value = meta.get(key)
            if value:
                return str(value)
        return None

    @staticmethod
    def _headers(extr, page_url: str) -> dict[str, str]:
        source = getattr(extr, "headers", None)
        if not source:
            session = getattr(extr, "session", None)
            source = getattr(session, "headers", None) if session is not None else None
        headers = {
            str(key): str(value)
            for key, value in dict(source or {}).items()
            if str(key).lower() not in HEADER_DROP
        }
        headers.setdefault("Referer", page_url)
        return headers

    @staticmethod
    def _get(client: httpx.Client, image_url: str, referer: str) -> bytes:
        try:
            response = client.get(image_url, headers={"Referer": referer})
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ScraperError(f"Falha ao baixar imagem: {exc}") from exc
        return response.content

    @staticmethod
    def _extension(image_url: str, meta: dict, data: bytes) -> str:
        extension = str(meta.get("extension") or "").strip().lstrip(".")
        if extension:
            return f".{extension}"
        return image_extension(image_url, data)
