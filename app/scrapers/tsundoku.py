"""Scraper de mangas/novels do site WordPress tsundoku.com.br (traducoes PT-BR).

A pagina da serie (`/manga/{slug}/`) lista todos os capitulos como links na
raiz do site no formato `/{series}-vol-N-cap-M-{titulo}/` ou
`/{series}-cap-NN-{titulo}/` (sem vol). O numero do capitulo e o numero apos
`cap-`. A pagina do capitulo e renderizada por JS (reader `#readerarea`), entao
o download usa Playwright para coletar as imagens do leitor.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from playwright.sync_api import BrowserContext, Page

from . import browser
from .base import DOWNLOADS_DIR, ProgressCb, Scraper, ScraperError
from .mangafire_parse import image_extension, make_cbz, sanitize

CHAPTER_NUM_RE = re.compile(r"cap-(\d+)", re.IGNORECASE)
CHAPTER_IMG_SELECTOR = "#readerarea img"
SKIP_IMG_RE = re.compile(
    r"logo|avatar|banner|emoji|gravatar|pixel\.wp|Apoio|TsunBranca|readerarea",
    re.IGNORECASE,
)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
NAV_TIMEOUT_MS = 45000
IMG_MAX_ITER = 60
IMG_WAIT_MS = 700
DELAY_S = 0.3

# O reader lazy-loada as paginas: imagem ainda nao carregada tem src =
# readerarea.svg (placeholder) e a URL real em data-src; carregada tem a URL
# real em currentSrc/src e data-src vazio. Usa data-src como fallback.
IMAGES_JS = (
    "els => els.map(e => {"
    "const cur = e.currentSrc || e.src || '';"
    "return cur.includes('readerarea.svg') ? (e.dataset.src || '') : cur;"
    "}).filter(u => u && u.startsWith('http'))"
)


def chapter_number(path: str) -> int | None:
    """Extrai o numero do capitulo do path (numero apos 'cap-')."""
    match = CHAPTER_NUM_RE.search(path or "")
    return int(match.group(1)) if match else None


def chapter_label(number: int) -> str:
    """Monta o rotulo do capitulo, ex: 'Cap. 315'."""
    return f"Cap. {number}"


def is_chapter_link(url: str, host: str) -> bool:
    """True se a URL e um link de capitulo do mesmo host com path de 1 segmento."""
    parsed = urlparse(url)
    if (parsed.hostname or "").lower() != host:
        return False
    path = (parsed.path or "").strip("/")
    if not path or "/" in path:
        return False
    return bool(CHAPTER_NUM_RE.search(path))


def order_ascending(items: list[dict]) -> list[dict]:
    """Ordena os itens em ordem crescente de numero de capitulo."""
    return sorted(items, key=lambda item: chapter_number(str(item.get("id", ""))) or 0)


class TsundokuScraper(Scraper):
    """Mangas (reader de imagens) e novels do tsundoku.com.br."""

    id = "tsundoku"
    label = "Tsundoku (PT-BR)"
    kind = "manga"

    def match(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return host == "tsundoku.com.br" or host == "www.tsundoku.com.br"

    def get_info(self, url: str) -> dict:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        series_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        try:
            with httpx.Client(
                headers={"User-Agent": USER_AGENT},
                follow_redirects=True,
                timeout=30,
            ) as client:
                response = client.get(series_url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ScraperError(f"Falha ao acessar a pagina da serie: {exc}") from exc
        soup = BeautifulSoup(response.content, "lxml")
        items: list[dict] = []
        seen: set[str] = set()
        for anchor in soup.select("a[href]"):
            href = anchor.get("href") or ""
            if not is_chapter_link(href, host):
                continue
            if href in seen:
                continue
            seen.add(href)
            number = chapter_number(href)
            if number is None:
                continue
            items.append({"id": href, "label": chapter_label(number)})
        if not items:
            raise ScraperError("Nenhum capitulo encontrado nesta pagina.")
        return {"title": self._title(soup, host), "cover": None, "items": order_ascending(items)}

    @staticmethod
    def _title(soup: BeautifulSoup, host: str) -> str:
        h1 = soup.find("h1")
        if h1 and h1.get_text(strip=True):
            return sanitize(h1.get_text(strip=True))
        meta = soup.select_one('meta[property="og:title"]')
        if meta and meta.get("content"):
            title = str(meta["content"]).split(" - ")[0].strip()
            return sanitize(title)
        return sanitize(host)

    def download(
        self,
        url: str,
        item_ids: list[str],
        progress_cb: ProgressCb,
        options: dict | None = None,
    ) -> None:
        options = options or {}
        info = self.get_info(url)
        title = sanitize(str(info["title"]))
        wanted = {str(item_id) for item_id in item_ids}
        ordered = [item for item in info["items"] if str(item.get("id")) in wanted]
        if not ordered:
            raise ScraperError("Nenhum capitulo valido foi selecionado.")
        total = len(ordered)
        with browser.run() as context:
            for index, item in enumerate(ordered, start=1):
                label = str(item["label"])
                progress_cb(
                    int((index - 1) / total * 100),
                    f"Iniciando capitulo {label} ({index}/{total})",
                )
                page = self._new_page(context)
                try:
                    self._download_chapter(
                        page,
                        DOWNLOADS_DIR / title,
                        index,
                        item,
                        progress_cb,
                        options,
                        total,
                    )
                finally:
                    page.close()
                progress_cb(
                    int(index / total * 100),
                    f"Concluido capitulo {label} ({index}/{total})",
                )

    @staticmethod
    def _new_page(context: BrowserContext) -> Page:
        page = context.new_page()
        page.set_default_timeout(30000)
        return page

    def _download_chapter(
        self,
        page: Page,
        base: Path,
        index: int,
        item: dict,
        progress_cb: ProgressCb,
        options: dict,
        total: int,
    ) -> None:
        label = str(item["label"])
        folder = base / f"{index:03d}_{sanitize(label)}"
        chapter_url = str(item["id"])
        try:
            page.goto(chapter_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            browser.scroll_until_stable(page, CHAPTER_IMG_SELECTOR, IMG_MAX_ITER, IMG_WAIT_MS)
            images = self._chapter_images(page)
        except Exception as exc:
            raise ScraperError(f"Falha ao ler o capitulo {label}: {exc}") from exc
        if not images:
            progress_cb(int((index - 1) / total * 100), f"Sem paginas em {label}")
            return
        if folder.exists() and self._page_count(folder) == len(images):
            progress_cb(int((index - 1) / total * 100), f"Capitulo {label} ja baixado, pulando")
            return
        folder.mkdir(parents=True, exist_ok=True)
        for position, image_url in enumerate(images, start=1):
            data = browser.download_binary(page, image_url)
            extension = image_extension(image_url, data)
            (folder / f"{position:03d}{extension}").write_bytes(data)
            percent = int(((index - 1) + position / len(images)) / total * 100)
            progress_cb(percent, f"Cap {label}/pg {position}")
            time.sleep(DELAY_S)
        if options.get("cbz"):
            make_cbz(folder)

    @staticmethod
    def _chapter_images(page: Page) -> list[str]:
        urls = page.eval_on_selector_all(CHAPTER_IMG_SELECTOR, IMAGES_JS)
        result: list[str] = []
        seen: set[str] = set()
        for url in urls:
            if not url or url in seen or SKIP_IMG_RE.search(url):
                continue
            seen.add(url)
            result.append(url)
        return result

    @staticmethod
    def _page_count(folder: Path) -> int:
        return sum(1 for entry in folder.iterdir() if entry.is_file())