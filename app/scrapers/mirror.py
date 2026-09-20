"""Espelho simples de site: baixa HTML e recursos do mesmo host.

NAO reescreve o HTML: os links permanecem absolutos (limitacao documentada).
So entra pelo modo forcado da UI (`force=mirror`), pois nunca e detectado
automaticamente. Opcoes: `depth` (profundidade do BFS, padrao 2) e
`max_pages` (limite de paginas, padrao 15).
"""
from __future__ import annotations

from collections import deque
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .base import DOWNLOADS_DIR, USER_AGENT, ProgressCb, Scraper, ScraperError
from .mangafire_parse import sanitize

MAX_PAGES_DEFAULT = 15
DEPTH_DEFAULT = 2
MAX_BINARY_BYTES = 200 * 1024 * 1024
RESOURCE_SELECTORS = ("img[src]", "script[src]", "link[href]", "source[src]")


class MirrorScraper(Scraper):
    """Espelho same-host de um site (HTML + recursos), so via modo forcado."""

    id = "mirror"
    label = "Espelho de site"
    kind = "site"

    def match(self, url: str) -> bool:
        # Espelho nunca e detectado automaticamente: so entra quando a UI
        # envia force=mirror. Retornar False mantem a ordem do registry.
        return False

    def get_info(self, url: str) -> dict:
        host = urlparse(url).netloc
        soup = self._soup(url)
        pages = self._same_host_links(soup, url, host)
        resources = self._resource_urls(soup, url)
        count = min(1 + len(pages), MAX_PAGES_DEFAULT)
        return {
            "title": f"Espelho de {host}",
            "cover": None,
            "items": [{"id": "1", "label": f"{count} paginas"}],
            "resources": len(resources),
        }

    def download(
        self,
        url: str,
        item_ids: list[str],
        progress_cb: ProgressCb,
        options: dict | None = None,
    ) -> None:
        options = options or {}
        depth = max(0, int(options.get("depth", DEPTH_DEFAULT)))
        max_pages = max(1, int(options.get("max_pages", MAX_PAGES_DEFAULT)))
        host = urlparse(url).netloc
        root = DOWNLOADS_DIR / "mirror" / sanitize(host)
        root.mkdir(parents=True, exist_ok=True)
        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque([(url, 0)])
        pages = 0
        with httpx.Client(
            headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=60
        ) as client:
            while queue and pages < max_pages:
                page_url, level = queue.popleft()
                if page_url in visited:
                    continue
                visited.add(page_url)
                html = self._fetch(client, page_url)
                self._save_page(root, page_url, html)
                pages += 1
                progress_cb(min(99, int(pages * 100 / max_pages)), f"Pagina {pages}: {page_url}")
                if level >= depth:
                    continue
                soup = BeautifulSoup(html, "lxml")
                self._save_resources(client, root, page_url, soup)
                for link in self._same_host_links(soup, page_url, host):
                    if link not in visited:
                        queue.append((link, level + 1))
        progress_cb(100, "Concluido")

    # -- helpers -------------------------------------------------------

    @staticmethod
    def _soup(url: str) -> BeautifulSoup:
        try:
            with httpx.Client(
                headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=30
            ) as client:
                response = client.get(url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ScraperError(f"Falha ao acessar {url}: {exc}") from exc
        return BeautifulSoup(response.text, "lxml")

    @staticmethod
    def _fetch(client: httpx.Client, url: str) -> bytes:
        try:
            response = client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ScraperError(f"Falha ao baixar {url}: {exc}") from exc
        return response.content

    @staticmethod
    def _same_host_links(soup: BeautifulSoup, base: str, host: str) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        base_clean = base.split("?")[0].split("#")[0].rstrip("/")
        for anchor in soup.select("a[href]"):
            absolute = urljoin(base, anchor.get("href") or "").split("?")[0].split("#")[0]
            parsed = urlparse(absolute)
            if parsed.scheme not in ("http", "https") or parsed.netloc != host:
                continue
            clean = absolute.rstrip("/") or absolute
            if clean == base_clean or clean in seen:
                continue
            seen.add(clean)
            result.append(clean)
        return result

    @staticmethod
    def _resource_urls(soup: BeautifulSoup, base: str) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for selector in RESOURCE_SELECTORS:
            for node in soup.select(selector):
                value = node.get("src") or node.get("href") or ""
                if not value or value.startswith("data:"):
                    continue
                absolute = urljoin(base, value).split("#")[0]
                if absolute not in seen:
                    seen.add(absolute)
                    result.append(absolute)
        return result

    @staticmethod
    def _save_page(root: Path, page_url: str, html: bytes) -> None:
        path = MirrorScraper._map_path(root, page_url)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(html)

    def _save_resources(
        self, client: httpx.Client, root: Path, page_url: str, soup: BeautifulSoup
    ) -> None:
        for resource in self._resource_urls(soup, page_url):
            path = self._map_path(root, resource)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._download_resource(client, resource, path)

    @staticmethod
    def _download_resource(client: httpx.Client, url: str, path: Path) -> None:
        try:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                total = int(response.headers.get("content-length") or 0)
                if total > MAX_BINARY_BYTES:
                    return
                written = 0
                with path.open("wb") as handle:
                    for chunk in response.iter_bytes(65536):
                        written += len(chunk)
                        if written > MAX_BINARY_BYTES:
                            break
                        handle.write(chunk)
            if written > MAX_BINARY_BYTES:
                path.unlink(missing_ok=True)
        except httpx.HTTPError:
            path.unlink(missing_ok=True)

    @staticmethod
    def _map_path(root: Path, url: str) -> Path:
        path = unquote(urlparse(url).path or "/")
        if path.endswith("/") or Path(path).suffix == "":
            path = path.rstrip("/") + "/index.html"
        segments = [sanitize(segment) for segment in path.split("/") if segment]
        return root.joinpath(*segments)
