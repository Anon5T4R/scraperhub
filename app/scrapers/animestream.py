"""Scraper de series de anime em 3 hosts (animeq, otakubr, animesdigital)."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from bs4 import BeautifulSoup

from .base import DOWNLOADS_DIR, ProgressCb, Scraper, ScraperError
from .deps import ensure_ffmpeg
from .animestream_net import USER_AGENT, ensure_folder, fetch, host, run_downloads, sanitize, ytdlp

HOSTS = ("animeq.cloud", "otakubr.com", "animesdigital.org")
MAX_PAGES = 30
MP4_RE = re.compile(r"https?://[^\"'\s]+\.mp4")
EPISODE_NUM_RE = re.compile(r"episodio-(\d+)$")
OTAKUBR_EP_RE = re.compile(r"^https?://[^/]+/anime/([^/]+)/(\d+)/(\d+)/?$")


class AnimeStreamScraper(Scraper):
    """Baixa series de anime de animeq.cloud, otakubr.com e animesdigital.org."""

    id = "animestream"
    label = "Anime (serie)"
    kind = "video"

    def match(self, url: str) -> bool:
        return host(url) in HOSTS

    def get_info(self, url: str) -> dict:
        host_name = host(url)
        if host_name == "animeq.cloud":
            return self._info_animeq(url)
        if host_name == "otakubr.com":
            return self._info_otakubr(url)
        return self._info_animesdigital(url)

    def download(
        self,
        url: str,
        item_ids: list[str],
        progress_cb: ProgressCb,
        options: dict | None = None,
    ) -> None:
        host_name = host(url)
        if host_name == "animeq.cloud":
            self._download_series(url, item_ids, progress_cb, self._info_animeq, self._episode_animeq)
        elif host_name == "otakubr.com":
            ffmpeg = ensure_ffmpeg()
            self._download_series(
                url,
                item_ids,
                progress_cb,
                self._info_otakubr,
                lambda ep, title, label, cb: self._episode_otakubr(ep, title, label, cb, ffmpeg),
            )
        else:
            ffmpeg = ensure_ffmpeg()
            self._download_series(
                url,
                item_ids,
                progress_cb,
                self._info_animesdigital,
                lambda ep, title, label, cb: self._episode_animesdigital(ep, title, label, cb, ffmpeg),
            )

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

    # -- animeq.cloud ---------------------------------------------------

    @staticmethod
    def _animeq_slug(url: str) -> str:
        parts = [p for p in urlparse(url).path.split("/") if p]
        if len(parts) >= 2 and parts[0] == "anime":
            return parts[1]
        raise ScraperError("URL de anime invalida (esperado /anime/{slug}).")

    @staticmethod
    def _episode_num(url: str) -> str:
        """Numero do episodio ou o sufixo da URL (ex: 'trailer')."""
        tail = url.rstrip("/").split("/")[-1]
        match = EPISODE_NUM_RE.search(tail)
        if match:
            return match.group(1)
        number = re.search(r"(\d+)$", tail)
        if number:
            return number.group(1)
        # sem numero (trailer, extra...): usa a ultima palavra do slug
        word = re.sub(r"[^a-z0-9-]", "", tail.split("-")[-1])
        return word or "extra"

    @staticmethod
    def _page_num(href: str, slug: str) -> int | None:
        match = re.search(rf"/anime/{re.escape(slug)}/(\d+)/?$", href)
        return int(match.group(1)) if match else None

    def _info_animeq(self, url: str) -> dict:
        slug = self._animeq_slug(url)
        base = f"https://animeq.cloud/anime/{slug}/"
        seen: set[str] = set()
        episodes: list[str] = []
        title = "Anime sem titulo"
        for page in range(1, MAX_PAGES + 1):
            page_url = base if page == 1 else f"{base}{page}/"
            soup = BeautifulSoup(fetch(page_url), "lxml")
            h1 = soup.find("h1")
            if h1 and h1.get_text(strip=True):
                title = h1.get_text(strip=True)
            for link in soup.select('a[href*="/episodio/"]'):
                href = link.get("href") or ""
                if href not in seen:
                    seen.add(href)
                    episodes.append(href)
            pagination = [
                self._page_num(a.get("href") or "", slug)
                for a in soup.select(f'a[href*="/anime/{slug}/"]')
            ]
            if page + 1 not in pagination:
                break
        items = [{"id": ep, "label": f"Ep {self._episode_num(ep)}"} for ep in episodes]
        if not items:
            raise ScraperError("Nenhum episodio encontrado nesta pagina.")
        return {"title": title, "cover": None, "items": items}

    def _episode_animeq(self, url: str, title: str, label: str, progress_cb: ProgressCb) -> None:
        html = fetch(url, referer=url)
        soup = BeautifulSoup(html, "lxml")
        source = self._animeq_source(soup, html)
        if not source:
            raise ScraperError("Nenhuma fonte de video encontrada")
        folder = ensure_folder(title)
        target = folder / sanitize(f"{label}.mp4")
        headers = {"User-Agent": USER_AGENT, "Referer": url}
        try:
            with httpx.Client(follow_redirects=True, timeout=600) as client:
                with client.stream("GET", source, headers=headers) as response:
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

    @staticmethod
    def _animeq_source(soup: BeautifulSoup, html: str) -> str | None:
        for video in soup.select("video"):
            src = video.get("src") or ""
            if src.endswith(".mp4"):
                return src
            for source in video.select("source"):
                ssrc = source.get("src") or ""
                if ssrc.endswith(".mp4"):
                    return ssrc
        match = MP4_RE.search(html)
        return match.group(0) if match else None

    # -- otakubr.com ----------------------------------------------------

    @staticmethod
    def _otakubr_slug(url: str) -> str:
        parts = [p for p in urlparse(url).path.split("/") if p]
        if len(parts) >= 2 and parts[0] == "anime":
            return parts[1]
        raise ScraperError("URL de anime invalida (esperado /anime/{slug}/...).")

    def _info_otakubr(self, url: str) -> dict:
        slug = self._otakubr_slug(url)
        soup = BeautifulSoup(fetch(url), "lxml")
        h1 = soup.find("h1")
        seen: set[str] = set()
        items: list[dict] = []
        for link in soup.select("a[href]"):
            href = link.get("href") or ""
            match = OTAKUBR_EP_RE.match(href)
            if not match or match.group(1) != slug or href in seen:
                continue
            seen.add(href)
            season, episode = match.group(2), match.group(3)
            items.append({"id": href, "label": f"S{season}E{int(episode):02d}"})
        if not items:
            raise ScraperError("Nenhum episodio encontrado nesta pagina.")
        meta = soup.select_one('meta[property="og:title"]')
        title = h1.get_text(strip=True) if h1 and h1.get_text(strip=True) else (
            meta.get("content") if meta and meta.get("content") else ""
        )
        return {"title": title or "Anime sem titulo", "cover": None, "items": items}

    def _episode_otakubr(self, url, title, label, progress_cb, ffmpeg: str | None) -> None:
        soup = BeautifulSoup(fetch(url), "lxml")
        iframe = soup.select_one('iframe[src*="blogger.com"]')
        if not iframe:
            raise ScraperError("Nenhuma fonte de video encontrada")
        try:
            ytdlp(
                iframe.get("src") or "",
                str(ensure_folder(title) / f"{label}.%(ext)s"),
                progress_cb,
                ffmpeg,
            )
        except ScraperError as exc:
            raise ScraperError(
                "O player Blogger deste site ainda nao e suportado para download "
                f"(player protegido). Detalhe: {str(exc)[-120:]}"
            ) from exc

    # -- animesdigital.org ----------------------------------------------

    def _info_animesdigital(self, url: str) -> dict:
        soup = BeautifulSoup(fetch(url), "lxml")
        h1 = soup.find("h1")
        seen: set[str] = set()
        links: list[str] = []
        for link in soup.select('a[href*="/video/a/"]'):
            href = link.get("href") or ""
            if "#" in href or href in seen:
                continue
            seen.add(href)
            links.append(href)
        items = [{"id": href, "label": f"Ep {index:02d}"} for index, href in enumerate(links, start=1)]
        if not items:
            raise ScraperError("Nenhum episodio encontrado nesta pagina.")
        return {
            "title": h1.get_text(strip=True) if h1 else "Anime sem titulo",
            "cover": None,
            "items": items,
        }

    def _episode_animesdigital(self, url, title, label, progress_cb, ffmpeg: str | None) -> None:
        soup = BeautifulSoup(fetch(url), "lxml")
        iframe = soup.select_one('iframe[src*="api.anivideo.net"]')
        if not iframe:
            raise ScraperError("Nenhuma fonte de video encontrada")
        src = iframe.get("src") or ""
        m3u8 = unquote(parse_qs(urlparse(src).query).get("d", [""])[0])
        if not m3u8:
            raise ScraperError("Nenhuma fonte de video encontrada")
        ytdlp(m3u8, str(ensure_folder(title) / f"{label}.%(ext)s"), progress_cb, ffmpeg)
