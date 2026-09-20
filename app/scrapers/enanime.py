"""Scraper de series de anime em agregadores EN (animeheaven, gogoanime, 9anime)."""
from __future__ import annotations

import base64
import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .animestream_net import USER_AGENT, ensure_folder, fetch, host, run_downloads, sanitize, ytdlp
from .base import DOWNLOADS_DIR, ProgressCb, Scraper, ScraperError
from .deps import ensure_ffmpeg

HOSTS = ("animeheaven.me", "gogoanime.is", "9anime.org.lv")

# regexes de episodio por host (constantes de modulo testaveis)
GOGOANIME_EP_RE = re.compile(r"^https?://[^/]+/([^/]+)-episode-(\d+)/?$")
NINEANIME_EP_RE = re.compile(r"^https?://[^/]+/([^/]+)-episode-(\d+)/?$")
ANIMEHEAVEN_GATE_RE = re.compile(r"^https?://[^/]+/gate\.php\?key=([a-f0-9]+)$")
ANIMEHEAVEN_EP_RE = re.compile(r'gatea\("([a-f0-9]+)"\)')
VIDMOLY_RE = re.compile(r"vidmoly\.(?:biz|to|cc|com|me)")
MIRROR_IFRAME_RE = re.compile(r'<iframe[^>]+src="([^"]+)"')


def animeheaven_key(url: str) -> str | None:
    """Extrai a chave do episodio de uma URL gate.php?key=... do animeheaven."""
    match = ANIMEHEAVEN_GATE_RE.match(url)
    return match.group(1) if match else None


def mirror_vidmoly(value: str) -> str | None:
    """Decodifica a opcao base64 do seletor de servidores e devolve a URL vidmoly."""
    if not value:
        return None
    try:
        decoded = base64.b64decode(value).decode()
    except ValueError:
        return None
    for src in MIRROR_IFRAME_RE.findall(decoded):
        if VIDMOLY_RE.search(src):
            return src
    return None


class EnAnimeScraper(Scraper):
    """Baixa series de anime de animeheaven.me, gogoanime.is e 9anime.org.lv."""

    id = "enanime"
    label = "Anime EN"
    kind = "video"

    def match(self, url: str) -> bool:
        return host(url) in HOSTS

    def get_info(self, url: str) -> dict:
        host_name = host(url)
        if host_name == "animeheaven.me":
            return self._info_animeheaven(url)
        if host_name == "gogoanime.is":
            return self._info_gogoanime(url)
        return self._info_9anime(url)

    def download(
        self,
        url: str,
        item_ids: list[str],
        progress_cb: ProgressCb,
        options: dict | None = None,
    ) -> None:
        host_name = host(url)
        if host_name == "animeheaven.me":
            self._download_series(url, item_ids, progress_cb, self._info_animeheaven, self._episode_animeheaven)
        elif host_name == "gogoanime.is":
            ffmpeg = ensure_ffmpeg()
            self._download_series(
                url,
                item_ids,
                progress_cb,
                self._info_gogoanime,
                lambda ep, title, label, cb: self._episode_gogoanime(ep, title, label, cb, ffmpeg),
            )
        else:
            ffmpeg = ensure_ffmpeg()
            self._download_series(
                url,
                item_ids,
                progress_cb,
                self._info_9anime,
                lambda ep, title, label, cb: self._episode_9anime(ep, title, label, cb, ffmpeg),
            )

    def first_source(self, episode_url: str) -> str | None:
        """Primeira fonte de video resolvivel do episodio (mp4/m3u8), ou None."""
        host_name = host(episode_url)
        if host_name == "animeheaven.me":
            key = animeheaven_key(episode_url)
            if not key:
                return None
            soup = BeautifulSoup(self._fetch_gate(key), "lxml")
            source = soup.select_one("video source[src*='.mp4']")
            return source.get("src") if source else None
        if host_name == "gogoanime.is":
            soup = BeautifulSoup(fetch(episode_url), "lxml")
            for link in soup.select("a[data-video]"):
                src = link.get("data-video") or ""
                if VIDMOLY_RE.search(src):
                    return src
            return None
        soup = BeautifulSoup(fetch(episode_url), "lxml")
        for opt in soup.select("select.mirror option"):
            src = mirror_vidmoly(opt.get("value") or "")
            if src:
                return src
        return None

    # -- comum ----------------------------------------------------------

    @staticmethod
    def _selected(info: dict, item_ids: list[str]) -> list[dict]:
        selected = [item for item in info["items"] if item["id"] in item_ids]
        if not selected:
            raise ScraperError("Nenhum episodio valido foi selecionado.")
        return selected

    def _download_series(
        self,
        url: str,
        item_ids: list[str],
        progress_cb: ProgressCb,
        info_fn,
        episode_fn,
    ) -> None:
        info = info_fn(url)
        title = sanitize(str(info["title"]))
        selected = self._selected(info, item_ids)
        DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
        run_downloads(
            selected,
            lambda ep, label: episode_fn(ep, title, label, progress_cb),
            progress_cb,
        )

    # -- animeheaven.me -------------------------------------------------

    @staticmethod
    def _fetch_gate(key: str) -> str:
        """Pagina do episodio do animeheaven (gate.php) com o cookie key."""
        headers = {"User-Agent": USER_AGENT, "Cookie": f"key={key}"}
        try:
            with httpx.Client(follow_redirects=True, timeout=30) as client:
                response = client.get("https://animeheaven.me/gate.php", headers=headers)
                response.raise_for_status()
                return response.text
        except httpx.HTTPError as exc:
            raise ScraperError(f"Falha ao acessar o episodio: {exc}") from exc

    def _info_animeheaven(self, url: str) -> dict:
        soup = BeautifulSoup(fetch(url), "lxml")
        title_el = soup.select_one(".infotitle")
        title = (
            title_el.get_text(strip=True)
            if title_el and title_el.get_text(strip=True)
            else "Anime sem titulo"
        )
        items: list[dict] = []
        seen: set[str] = set()
        for link in soup.select("a[href]"):
            href = link.get("href") or ""
            if "gate.php" not in href:
                continue
            match = ANIMEHEAVEN_EP_RE.search(link.get("onclick") or "")
            if not match:
                continue
            key = match.group(1)
            if key in seen:
                continue
            seen.add(key)
            text = link.get_text(" ", strip=True)
            numero = re.search(r"Episode\s+(\d+)", text, re.I)
            label = f"Ep {int(numero.group(1)):02d}" if numero else f"Ep {key[:8]}"
            items.append({"id": f"https://animeheaven.me/gate.php?key={key}", "label": label})
        if not items:
            raise ScraperError("Nenhum episodio encontrado nesta pagina.")
        return {"title": title, "cover": None, "items": items}

    def _episode_animeheaven(self, url, title, label, progress_cb) -> None:
        key = animeheaven_key(url)
        if not key:
            raise ScraperError("URL de episodio invalida (esperado gate.php?key=...).")
        soup = BeautifulSoup(self._fetch_gate(key), "lxml")
        source = soup.select_one("video source[src*='.mp4']")
        if not source:
            raise ScraperError(
                "Nenhuma fonte de video direta neste episodio do animeheaven "
                "(video removido ou player indisponivel)."
            )
        mp4 = source.get("src") or ""
        folder = ensure_folder(title)
        target = folder / sanitize(f"{label}.mp4")
        headers = {"User-Agent": USER_AGENT, "Referer": "https://animeheaven.me/gate.php"}
        try:
            with httpx.Client(follow_redirects=True, timeout=600) as client:
                with client.stream("GET", mp4, headers=headers) as response:
                    response.raise_for_status()
                    total = int(response.headers.get("content-length") or 0)
                    done = 0
                    with target.open("wb") as handle:
                        for chunk in response.iter_bytes():
                            handle.write(chunk)
                            done += len(chunk)
                            percent = int(done * 100 / total) if total else 0
                            progress_cb(percent, f"Baixando {label}.mp4... {percent}%")
        except httpx.HTTPError as exc:
            raise ScraperError(f"Falha ao baixar o episodio: {exc}") from exc

    # -- gogoanime.is ---------------------------------------------------

    def _info_gogoanime(self, url: str) -> dict:
        slug = urlparse(url).path.rstrip("/").split("/")[-1]
        soup = BeautifulSoup(fetch(url), "lxml")
        h1 = soup.find("h1")
        items: list[dict] = []
        seen: set[str] = set()
        for link in soup.select('a[href*="-episode-"]'):
            href = link.get("href") or ""
            absolute = urljoin(url, href)
            match = GOGOANIME_EP_RE.match(absolute)
            if not match or match.group(1) != slug or absolute in seen:
                continue
            seen.add(absolute)
            items.append({"id": absolute, "label": f"Ep {int(match.group(2)):02d}"})
        if not items:
            raise ScraperError("Nenhum episodio encontrado nesta pagina.")
        return {
            "title": h1.get_text(strip=True) if h1 and h1.get_text(strip=True) else "Anime sem titulo",
            "cover": None,
            "items": items,
        }

    def _episode_gogoanime(self, url, title, label, progress_cb, ffmpeg: str | None) -> None:
        soup = BeautifulSoup(fetch(url), "lxml")
        vidmoly = None
        for link in soup.select("a[data-video]"):
            src = link.get("data-video") or ""
            if VIDMOLY_RE.search(src):
                vidmoly = src
                break
        if not vidmoly:
            raise ScraperError(
                "Nenhum servidor viavel (vidmoly) neste episodio do gogoanime "
                "(players restantes sao protegidos)."
            )
        ytdlp(vidmoly, str(ensure_folder(title) / f"{label}.%(ext)s"), progress_cb, ffmpeg)

    # -- 9anime.org.lv --------------------------------------------------

    def _info_9anime(self, url: str) -> dict:
        slug = urlparse(url).path.rstrip("/").split("/")[-1]
        soup = BeautifulSoup(fetch(url), "lxml")
        h1 = soup.find("h1")
        items: list[dict] = []
        seen: set[str] = set()
        for link in soup.select(".eplister ul li a"):
            href = link.get("href") or ""
            absolute = urljoin(url, href)
            match = NINEANIME_EP_RE.match(absolute)
            if not match or match.group(1) != slug or absolute in seen:
                continue
            seen.add(absolute)
            items.append({"id": absolute, "label": f"Ep {int(match.group(2)):02d}"})
        if not items:
            raise ScraperError("Nenhum episodio encontrado nesta pagina.")
        return {
            "title": h1.get_text(strip=True) if h1 and h1.get_text(strip=True) else "Anime sem titulo",
            "cover": None,
            "items": items,
        }

    def _episode_9anime(self, url, title, label, progress_cb, ffmpeg: str | None) -> None:
        soup = BeautifulSoup(fetch(url), "lxml")
        vidmoly = None
        for opt in soup.select("select.mirror option"):
            vidmoly = mirror_vidmoly(opt.get("value") or "")
            if vidmoly:
                break
        if not vidmoly:
            raise ScraperError(
                "Nenhum servidor viavel (vidmoly) neste episodio do 9anime "
                "(players restantes sao protegidos)."
            )
        ytdlp(vidmoly, str(ensure_folder(title) / f"{label}.%(ext)s"), progress_cb, ffmpeg)
