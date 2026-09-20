"""Scraper de arquivos e file hosts (Google Drive, MediaFire, links diretos)."""
from __future__ import annotations

import re
from urllib.parse import unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .animestream_net import retry_call
from .base import DOWNLOADS_DIR, USER_AGENT, ProgressCb, Scraper, ScraperError
from .mangafire_parse import sanitize

FILE_EXTS = (".zip", ".rar", ".7z", ".iso", ".tar", ".gz", ".mp4")
DRIVE_ID_RE = re.compile(r"[-\w]{25,}")
MEDIAFIRE_SELECTORS = ("a.download_btn", "a#downloadButton", "a.input.popsok")
MEDIAFIRE_HREF_RE = re.compile(r'href=["\'](https?://download[^"\']+)["\']', re.IGNORECASE)


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


class FileHostScraper(Scraper):
    """Arquivos hospedados no Google Drive, MediaFire ou link direto."""

    id = "filehost"
    label = "Arquivo/File host"
    kind = "file"

    def match(self, url: str) -> bool:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if "mega.nz" in host:
            return True
        if host == "drive.google.com" or host == "mediafire.com" or host.endswith(".mediafire.com"):
            return True
        if host == "docs.google.com" and (parsed.path or "").startswith("/uc"):
            return True
        return (parsed.path or "").lower().endswith(FILE_EXTS)

    def get_info(self, url: str) -> dict:
        host = (urlparse(url).hostname or "").lower()
        if self._is_drive(url):
            if not DRIVE_ID_RE.search(url):
                raise ScraperError("Nao foi possivel extrair o id do arquivo do Google Drive.")
            return {"title": "Google Drive", "cover": None, "items": [{"id": url, "label": "Google Drive"}]}
        if "mediafire" in host:
            title = self._mediafire_title(url)
            return {"title": title, "cover": None, "items": [{"id": url, "label": title}]}
        name = self._filename(url)
        size = self._content_length(url)
        label = f"{name} ({size})" if size else name
        return {"title": name, "cover": None, "items": [{"id": url, "label": label}]}

    def download(
        self,
        url: str,
        item_ids: list[str],
        progress_cb: ProgressCb,
        options: dict | None = None,
    ) -> None:
        host = (urlparse(url).hostname or "").lower()
        target = str(item_ids[0]) if item_ids else url
        if "://" not in target:
            target = url
        if "mega.nz" in host:
            raise ScraperError("Mega ainda nao suportado.")
        if self._is_drive(url):
            self._download_drive(target, progress_cb)
        elif "mediafire" in host:
            self._download_mediafire(target, progress_cb)
        else:
            self._download_stream(target, self._filename(target), progress_cb)
        progress_cb(100, "Concluido")

    # -- helpers -------------------------------------------------------

    @staticmethod
    def _is_drive(url: str) -> bool:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        return host == "drive.google.com" or (
            host == "docs.google.com" and (parsed.path or "").startswith("/uc")
        )

    @staticmethod
    def _download_drive(url: str, progress_cb: ProgressCb) -> None:
        import gdown

        out = DOWNLOADS_DIR / "filehost"
        out.mkdir(parents=True, exist_ok=True)
        progress_cb(0, "Baixando do Google Drive...")

        def download() -> str | None:
            try:
                return gdown.download(url=url, output=str(out) + "/", quiet=True)
            except Exception as exc:  # gdown levanta variados tipos
                raise ScraperError(f"Falha no download do Google Drive: {exc}") from exc

        result = retry_call(
            download,
            attempts=3,
            wait_s=5,
            on_retry=lambda tentativa, exc: progress_cb(
                0,
                f"falhou (tentativa {tentativa}/3): {str(exc)[-80:]} — repetindo",
            ),
        )
        if not result:
            raise ScraperError(
                "gdown nao conseguiu baixar este arquivo (link privado ou cota excedida?)."
            )

    def _download_mediafire(self, url: str, progress_cb: ProgressCb) -> None:
        direct = self._mediafire_direct(url)
        self._download_stream(direct, self._filename(direct), progress_cb)

    @staticmethod
    def _resolve_redirects(url: str) -> str:
        """Segue redirects manualmente (Location relativo quebra o stream do httpx)."""
        current = url
        for _ in range(10):
            try:
                with httpx.Client(
                    headers={"User-Agent": USER_AGENT},
                    follow_redirects=False,
                    timeout=30,
                ) as client:
                    response = client.head(current)
            except httpx.HTTPError:
                # servidor que nao responde HEAD (405/403): o GET com
                # follow_redirects do _download_stream resolve o redirect
                return url
            location = response.headers.get("location")
            if not location or response.status_code not in (301, 302, 303, 307, 308):
                return current
            current = str(urljoin(current, location))
        return current

    @staticmethod
    def _download_stream(url: str, filename: str, progress_cb: ProgressCb) -> None:
        out = DOWNLOADS_DIR / "filehost"
        out.mkdir(parents=True, exist_ok=True)
        path = out / sanitize(filename)
        final_url = FileHostScraper._resolve_redirects(url)
        percent = 0

        def stream() -> None:
            nonlocal percent
            with httpx.Client(
                headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=120
            ) as client:
                with client.stream("GET", final_url) as response:
                    response.raise_for_status()
                    total = int(response.headers.get("content-length") or 0)
                    done = 0
                    with path.open("wb") as handle:
                        for chunk in response.iter_bytes(65536):
                            handle.write(chunk)
                            done += len(chunk)
                            percent = int(done * 100 / total) if total else 0
                            progress_cb(percent, f"Baixando {filename}... {percent}%")

        try:
            retry_call(
                stream,
                attempts=3,
                wait_s=5,
                on_retry=lambda tentativa, exc: progress_cb(
                    percent,
                    f"falhou (tentativa {tentativa}/3): {str(exc)[-80:]} — repetindo",
                ),
            )
        except httpx.HTTPError as exc:
            path.unlink(missing_ok=True)
            raise ScraperError(f"Falha ao baixar o arquivo: {exc}") from exc

    @staticmethod
    def _mediafire_title(url: str) -> str:
        soup = FileHostScraper._soup(url)
        meta = soup.select_one('meta[property="og:title"]')
        if meta and meta.get("content"):
            return sanitize(str(meta["content"]))
        button = soup.select_one("a.download_btn")
        if button and button.get_text(strip=True):
            return sanitize(button.get_text(strip=True))
        return "MediaFire"

    @staticmethod
    def _mediafire_direct(url: str) -> str:
        soup = FileHostScraper._soup(url)
        for selector in MEDIAFIRE_SELECTORS:
            anchor = soup.select_one(selector)
            if anchor and anchor.get("href"):
                return urljoin(url, str(anchor["href"]))
        match = MEDIAFIRE_HREF_RE.search(str(soup))
        if match:
            return match.group(1)
        raise ScraperError("Nao foi possivel resolver o link direto do MediaFire.")

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
    def _content_length(url: str) -> str:
        try:
            with httpx.Client(
                headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=30
            ) as client:
                response = client.head(url)
                value = response.headers.get("content-length")
        except (httpx.HTTPError, ValueError):
            return ""
        return _human_size(int(value)) if value else ""

    @staticmethod
    def _filename(url: str) -> str:
        path = urlparse(url).path
        name = unquote(path.rsplit("/", 1)[-1]) if path else ""
        return sanitize(name) or "arquivo"
