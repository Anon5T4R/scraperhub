"""Scraper de mangas cuja PAGINA DA SERIE lista os capitulos.

Diferente do wpmanga (que lista capitulos da HOME do site), aqui a lista
vem da propria pagina da serie. Confirmado no asurascans.com:
- serie:   /comics/{slug} (HTML server-rendered, 100+ links de capitulo)
- capitulo:/comics/{slug}/chapter/{n}
- imagens: `main img` cuja URL contem "/chapters/" (capas ficam em /covers/,
  banners em /banners/ - ambos filtrados).
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .base import DOWNLOADS_DIR, ProgressCb, Scraper, ScraperError, USER_AGENT
from .mangafire_parse import image_extension, make_cbz, sanitize
from .animestream_net import retry_call

# Config por host: como a pagina de serie/capitulo se parece.
SITES: dict[str, dict[str, str]] = {
    "asurascans.com": {
        # trecho que identifica a URL de uma imagem de CONTEUDO no capitulo
        # (capas/banners do site ficam em outros caminhos do CDN)
        "img_marker": "/chapters/",
    },
}
SERIES_PATH_RE = re.compile(r"^/comics/[^/?#]+/?$", re.IGNORECASE)
CHAPTER_PATH_RE = re.compile(r"^/comics/([^/?#]+)/chapter/([^/?#]+)/?$", re.IGNORECASE)
CHAPTER_HREF_RE = re.compile(r"/comics/([^/?#]+)/chapter/([\d]+(?:\.\d+)?)", re.IGNORECASE)
REQUEST_GAP_S = 0.3


class SeriesMangaScraper(Scraper):
    """Mangas cuja pagina de serie lista os capitulos (asurascans e afins)."""

    id = "seriesmanga"
    label = "Manga (pagina de serie)"
    kind = "manga"

    def match(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower().removeprefix("www.")
        return host in SITES

    # -- helpers -------------------------------------------------------

    @staticmethod
    def _series_url(url: str) -> str:
        """Normaliza uma URL de serie ou capitulo para a URL da serie."""
        parsed = urlparse(url)
        path = parsed.path or ""
        match = CHAPTER_PATH_RE.match(path)
        if match:
            path = f"/comics/{match.group(1)}"
        return f"{parsed.scheme}://{parsed.netloc}{path.rstrip('/')}"

    def _get(self, client: httpx.Client, url: str, referer: str | None = None) -> BeautifulSoup:
        return self._fetch(client, url, referer)[0]

    def _fetch(
        self, client: httpx.Client, url: str, referer: str | None = None
    ) -> tuple[BeautifulSoup, str]:
        """GET com retry; retorna (soup, URL final apos redirects)."""
        headers = {"User-Agent": USER_AGENT}
        if referer:
            headers["Referer"] = referer
        final_url = url

        def fetch() -> tuple[BeautifulSoup, str]:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            return BeautifulSoup(response.text, "lxml"), str(response.url)

        try:
            soup, final_url = retry_call(fetch, attempts=3, wait_s=5)
        except httpx.HTTPError as exc:
            raise ScraperError(f"Falha ao acessar {url}: {exc}") from exc
        return soup, final_url

    @staticmethod
    def _chapter_images(soup: BeautifulSoup, img_marker: str) -> list[str]:
        urls: list[str] = []
        for img in soup.select("main img, article img"):
            src = img.get("src") or img.get("data-src") or ""
            if not src or src.startswith("data:"):
                continue
            if img_marker not in src:
                continue  # capa/banner/avatar: so pagina de conteudo interessa
            if src not in urls:
                urls.append(src)
        return urls

    # -- interface -----------------------------------------------------

    def get_info(self, url: str) -> dict:
        series_url = self._series_url(url)
        host = (urlparse(series_url).hostname or "").lower().removeprefix("www.")
        marker = SITES[host]["img_marker"]
        with httpx.Client(follow_redirects=True, timeout=30) as client:
            soup, final_url = self._fetch(client, series_url)
            # o site pode redirecionar p/ slug canônico (ex: -53fc8424):
            # os links de capitulo usam o slug final
            slug_match = re.search(r"/comics/([^/?#]+)", urlparse(final_url).path or "")
            slug = slug_match.group(1).lower() if slug_match else ""
            h1 = soup.select_one("h1")
            title = h1.get_text(" ", strip=True) if h1 else host
            cover_el = soup.select_one('meta[property="og:image"]')
            cover = cover_el.get("content") if cover_el else None
            items: list[dict] = []
            seen: set[str] = set()
            for anchor in soup.select("a[href]"):
                href = anchor.get("href") or ""
                absolute = urljoin(series_url, href).split("?")[0].split("#")[0]
                match = CHAPTER_HREF_RE.search(absolute)
                # so capitulos DESTA serie (a pagina tem recomendacoes de outras)
                if not match or match.group(1).lower() != slug or absolute in seen:
                    continue
                seen.add(absolute)
                items.append({"id": absolute, "label": f"Cap. {match.group(2)}"})
        if not items:
            raise ScraperError(
                "Nenhum capitulo encontrado na pagina da serie "
                "(esperados links /comics/{slug}/chapter/{n})."
            )

        def chapter_key(item: dict) -> float:
            match = re.search(r"([\d]+(?:\.\d+)?)", str(item["label"]))
            return float(match.group(1)) if match else -1.0

        items.sort(key=chapter_key, reverse=True)  # mais novo primeiro
        return {"title": sanitize(title) or host, "cover": cover, "items": items}

    def download(
        self,
        url: str,
        item_ids: list[str],
        progress_cb: ProgressCb,
        options: dict | None = None,
    ) -> None:
        options = options or {}
        info = self.get_info(url)
        wanted = {str(i) for i in item_ids}
        chosen = [i for i in info["items"] if str(i["id"]) in wanted]
        chosen.reverse()  # ordem crescente (site lista do mais novo pro mais velho)
        total = len(chosen)
        if total == 0:
            raise ScraperError("Nenhum capitulo selecionado.")

        host = (urlparse(url).hostname or "").lower().removeprefix("www.")
        marker = SITES[host]["img_marker"]
        root = DOWNLOADS_DIR / info["title"]
        falhas: list[str] = []
        done = 0
        with httpx.Client(follow_redirects=True, timeout=60) as client:
            for item in chosen:
                label = str(item["label"])
                chapter_url = str(item["id"])
                progress_cb(
                    int(done * 100 / total), f"Iniciando capitulo {label} ({done + 1}/{total})"
                )
                try:
                    soup = self._get(client, chapter_url, referer=self._series_url(url))
                    images = self._chapter_images(soup, marker)
                    if not images:
                        raise ScraperError("reader sem imagens de conteudo")
                except ScraperError as exc:
                    falhas.append(f"{label}: {str(exc)[-100:]}")
                    progress_cb(int(done * 100 / total), f"Falhou {label}: {str(exc)[-100:]}")
                    continue
                folder = root / sanitize(label.replace("Cap. ", "Ch_"))
                existing = list(folder.glob("*.[jp][pn]g")) + list(folder.glob("*.webp"))
                if len(existing) >= len(images):
                    progress_cb(
                        int((done + 1) * 100 / total),
                        f"Capitulo {label} ja baixado, pulando",
                    )
                    done += 1
                    continue
                folder.mkdir(parents=True, exist_ok=True)
                for index, image_url in enumerate(images, start=1):
                    try:

                        def fetch_image(u: str = image_url) -> bytes:
                            response = client.get(
                                u, headers={"Referer": self._series_url(url)}
                            )
                            response.raise_for_status()
                            return response.content

                        data = retry_call(fetch_image, attempts=3, wait_s=5)
                    except httpx.HTTPError as exc:
                        falhas.append(f"{label}: pagina {index} falhou ({exc})")
                        break
                    extension = image_extension(image_url, data)
                    (folder / f"{index:03d}{extension}").write_bytes(data)
                    progress_cb(
                        int((done + 1) * 100 / total),
                        f"{label}/pg {index}/{len(images)}",
                    )
                    time.sleep(REQUEST_GAP_S)
                if options.get("cbz"):
                    make_cbz(folder)
                done += 1
        if falhas:
            raise ScraperError(
                f"{len(falhas)}/{total} capitulo(s) falharam: " + "; ".join(falhas[:10])
            )
        progress_cb(100, "Concluido")
