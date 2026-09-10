"""Scraper de e-books: links diretos e paginas com varios arquivos.

Aceita URL direta com extensao de e-book ou o modo forcado da UI
(`?force=ebook`). Conteudo com DRM (Adobe/Kindle) e recusado com erro
amigavel: o ScraperHub nao burla protecao.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .base import DOWNLOADS_DIR, ProgressCb, Scraper, ScraperError
from .mangafire_parse import sanitize

EBOOK_EXTS = (".epub", ".pdf", ".mobi", ".azw3", ".fb2")
PROTECTED_EXTS = (".acsm", ".azw", ".azw3", ".prc")
KINDLE_MAGIC = b"\xca\xfe\xba\xbe"
DRM_MARKERS = (b"drm", b"encrypted")
MAX_LINKS = 200
DRM_MESSAGE = (
    "Conteudo protegido por DRM (Adobe/Kindle). "
    "O ScraperHub nao realiza download de conteudo com DRM."
)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class EbookScraper(Scraper):
    """E-books por link direto ou listados em uma pagina HTML."""

    id = "ebook"
    label = "E-book"
    kind = "ebook"

    def match(self, url: str) -> bool:
        parsed = urlparse(url)
        if "force=ebook" in (parsed.query or "").lower():
            return True
        return (parsed.path or "").lower().endswith(EBOOK_EXTS)

    def get_info(self, url: str) -> dict:
        if self._is_direct(url):
            name = self._filename(url)
            return {"title": name, "cover": None, "items": [{"id": url, "label": name}]}
        with httpx.Client(
            headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=30
        ) as client:
            html = self._fetch(client, url)
        soup = BeautifulSoup(html, "lxml")
        links = self._collect_links(soup, url)
        if not links:
            raise ScraperError("Nenhum e-book encontrado nesta pagina.")
        page_title = soup.title.get_text(strip=True) if soup.title else ""
        title = sanitize(page_title or urlparse(url).netloc or "ebooks")
        items = [{"id": link, "label": self._filename(link)} for link in links]
        return {"title": title, "cover": None, "items": items}

    def download(
        self,
        url: str,
        item_ids: list[str],
        progress_cb: ProgressCb,
        options: dict | None = None,
    ) -> None:
        targets = [str(item) for item in item_ids]
        if not targets:
            targets = [url] if self._is_direct(url) else [
                item["id"] for item in self.get_info(url)["items"]
            ]
        out = DOWNLOADS_DIR / "ebooks"
        out.mkdir(parents=True, exist_ok=True)
        total = len(targets)
        with httpx.Client(
            headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=60
        ) as client:
            for index, target in enumerate(targets, start=1):
                name = self._filename(target)
                extension = Path(name).suffix.lower()
                progress_cb(int((index - 1) * 100 / total), f"Baixando {name}")
                if extension in PROTECTED_EXTS:
                    raise ScraperError(DRM_MESSAGE)
                data = self._fetch(client, target)
                self._check_drm(extension, data)
                (out / sanitize(name)).write_bytes(data)
                progress_cb(int(index * 100 / total), f"{name} salvo")
        progress_cb(100, "Concluido")

    # -- helpers -------------------------------------------------------

    @staticmethod
    def _is_direct(url: str) -> bool:
        return (urlparse(url).path or "").lower().endswith(EBOOK_EXTS)

    @staticmethod
    def _collect_links(soup: BeautifulSoup, base: str) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for anchor in soup.select("a[href]"):
            href = anchor.get("href") or ""
            absolute = urljoin(base, href).split("?")[0].split("#")[0]
            if not absolute.lower().endswith(EBOOK_EXTS) or absolute in seen:
                continue
            seen.add(absolute)
            result.append(absolute)
            if len(result) >= MAX_LINKS:
                break
        return result

    @staticmethod
    def _check_drm(extension: str, data: bytes) -> None:
        if extension in PROTECTED_EXTS:
            raise ScraperError(DRM_MESSAGE)
        head = data[:4096]
        if head[:4] == KINDLE_MAGIC and any(marker in head.lower() for marker in DRM_MARKERS):
            raise ScraperError(DRM_MESSAGE)

    @staticmethod
    def _fetch(client: httpx.Client, url: str) -> bytes:
        try:
            response = client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ScraperError(f"Falha ao acessar {url}: {exc}") from exc
        return response.content

    @staticmethod
    def _filename(url: str) -> str:
        path = urlparse(url).path
        name = unquote(path.rsplit("/", 1)[-1]) if path else ""
        name = sanitize(name) or "ebook"
        # extensao dupla do Gutenberg (ex: 1342.epub.noimages -> 1342.epub):
        # se o sufixo final nao e uma extensao valida, corta na que for
        parts = name.split(".")
        if len(parts) > 2:
            for index in range(1, len(parts)):
                if ".".join(parts[index:]) in EXTENSIONS:
                    return ".".join(parts[: index + 1])
        return name
