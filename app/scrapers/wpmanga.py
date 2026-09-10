"""Scraper de mangas em sites WordPress server-rendered.

Funciona com sites cuja home lista os capitulos como links `/manga/{slug}`
e cujas paginas de capitulo trazem as imagens dentro do artigo
(`.entry-content` / `article` / `main`). Confirmado em
w2.chainsmokercat.website (289 capitulos listados na home, sem paginacao).
"""
from __future__ import annotations

import re
import time
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .base import DOWNLOADS_DIR, ProgressCb, Scraper, ScraperError
from .mangafire_parse import image_extension, make_cbz, sanitize

CHAPTER_HREF_RE = re.compile(r"/manga/[^/]*chapter-[\d]+(?:-[\d]+)?/?$", re.IGNORECASE)
CHAPTER_NUM_RE = re.compile(r"chapter-([\d]+(?:-[\d]+)?)/?$", re.IGNORECASE)
CONTENT_SELECTORS = (".entry-content img", "article img", "main img")
SKIP_IMG_RE = re.compile(r"kofi|ko-fi|cup-border|logo|avatar|banner|ads", re.IGNORECASE)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
REQUEST_GAP_S = 0.3


class WpMangaScraper(Scraper):
    """Mangas em WordPress: lista na home, imagens no artigo do capitulo."""

    id = "wpmanga"
    label = "Manga WordPress"
    kind = "manga"

    def match(self, url: str) -> bool:
        path = (urlparse(url).path or "").strip("/")
        if "/manga/" in f"/{path}":
            return True
        # home do site (sem caminho): aceita e valida na analise
        return path == ""

    # -- helpers -------------------------------------------------------

    @staticmethod
    def _homepage(url: str) -> str:
        parsed = urlparse(url)
        if parsed.path and parsed.path != "/":
            # link de capitulo -> raiz do site
            return f"{parsed.scheme}://{parsed.netloc}/"
        return f"{parsed.scheme}://{parsed.netloc}/"

    def _get(self, client: httpx.Client, url: str) -> BeautifulSoup:
        try:
            response = client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ScraperError(f"Falha ao acessar {url}: {exc}") from exc
        return BeautifulSoup(response.text, "lxml")

    @staticmethod
    def _site_title(soup: BeautifulSoup, fallback_host: str) -> str:
        title = soup.title.get_text(strip=True) if soup.title else ""
        for suffix in (" Manga Online", " - Read Manga", " Manga"):
            if title.endswith(suffix):
                title = title[: -len(suffix)]
        return sanitize(title.strip() or fallback_host)

    @staticmethod
    def _chapter_images(soup: BeautifulSoup) -> list[str]:
        urls: list[str] = []
        for selector in CONTENT_SELECTORS:
            for img in soup.select(selector):
                src = img.get("src") or img.get("data-src") or ""
                if not src or src.startswith("data:"):
                    continue
                if SKIP_IMG_RE.search(src):
                    continue
                if src not in urls:
                    urls.append(src)
            if urls:
                return urls
        return urls

    @staticmethod
    def _label(href: str, text: str) -> str:
        match = CHAPTER_NUM_RE.search(href)
        if match:
            return f"Cap. {match.group(1).replace('-', '.')}"
        return sanitize(text.strip()) or href.rsplit("/", 1)[-1]

    # -- interface -----------------------------------------------------

    def get_info(self, url: str) -> dict:
        home = self._homepage(url)
        with httpx.Client(
            headers={"User-Agent": USER_AGENT, "Referer": home},
            follow_redirects=True,
            timeout=30,
        ) as client:
            soup = self._get(client, home)
            title = self._site_title(soup, urlparse(home).netloc)
            seen: set[str] = set()
            items: list[dict] = []
            for anchor in soup.select('a[href*="/manga/"]'):
                href = anchor.get("href") or ""
                absolute = urljoin(home, href)
                if not CHAPTER_HREF_RE.search(absolute):
                    continue
                chapter_url = absolute.split("?")[0].rstrip("/")
                if chapter_url in seen:
                    continue
                seen.add(chapter_url)
                items.append(
                    {
                        "id": chapter_url,
                        "label": self._label(chapter_url, anchor.get_text()),
                    }
                )
        if not items:
            raise ScraperError(
                "Nenhum capitulo encontrado nesta home (esperados links /manga/...-chapter-N)."
            )
        return {"title": title, "cover": None, "items": items}

    def download(
        self,
        url: str,
        item_ids: list[str],
        progress_cb: ProgressCb,
        options: dict | None = None,
    ) -> None:
        options = options or {}
        info = self.get_info(url)
        wanted = [i for i in info["items"] if i["id"] in set(item_ids)]
        wanted.reverse()  # ordem crescente (site lista do mais novo pro mais velho)
        total = len(wanted)
        if total == 0:
            raise ScraperError("Nenhum capitulo selecionado.")

        root = DOWNLOADS_DIR / info["title"]
        done = 0
        with httpx.Client(
            headers={"User-Agent": USER_AGENT, "Referer": self._homepage(url)},
            follow_redirects=True,
            timeout=60,
        ) as client:
            for item in wanted:
                chapter_url = item["id"]
                progress_cb(
                    int(done * 100 / total),
                    f"Iniciando capitulo {item['label']} ({done + 1}/{total})",
                )
                soup = self._get(client, chapter_url)
                images = self._chapter_images(soup)
                if not images:
                    raise ScraperError(f"Sem imagens em {chapter_url}")

                num = CHAPTER_NUM_RE.search(chapter_url)
                folder_name = f"Ch_{num.group(1)}" if num else sanitize(item["label"])
                folder = root / sanitize(f"{folder_name}")
                existing = list(folder.glob("*.[jp][pn]g")) + list(folder.glob("*.webp"))
                if len(existing) >= len(images):
                    progress_cb(
                        int((done + 1) * 100 / total),
                        f"Capitulo {item['label']} ja baixado, pulando",
                    )
                    done += 1
                    continue

                folder.mkdir(parents=True, exist_ok=True)
                for index, image_url in enumerate(images, start=1):
                    try:
                        response = client.get(image_url)
                        response.raise_for_status()
                    except httpx.HTTPError as exc:
                        raise ScraperError(f"Falha ao baixar pagina {index}: {exc}") from exc
                    ext = image_extension(image_url, response.content)
                    (folder / f"{index:03d}{ext}").write_bytes(response.content)
                    progress_cb(
                        int((done + 1) * 100 / total),
                        f"{item['label']}/pg {index}/{len(images)}",
                    )
                    time.sleep(REQUEST_GAP_S)

                if options.get("cbz"):
                    make_cbz(folder)
                done += 1

        progress_cb(100, "Concluido")
