"""Scraper de series de anime em 4 hosts (animeq, otakubr, animesdigital, animexnovel)."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from . import browser
from .base import DOWNLOADS_DIR, ProgressCb, Scraper, ScraperError
from .deps import ensure_ffmpeg
from .animestream_net import USER_AGENT, ensure_folder, fetch, host, run_downloads, sanitize, ytdlp

HOSTS = ("animeq.cloud", "otakubr.com", "animesdigital.org", "animexnovel.com")
MAX_PAGES = 30
MP4_RE = re.compile(r"https?://[^\"'\s]+\.mp4")
EPISODE_NUM_RE = re.compile(r"episodio-(\d+)$")
OTAKUBR_EP_RE = re.compile(r"^https?://[^/]+/anime/([^/]+)/(\d+)/(\d+)/?$")
ANIMEXNOVEL_EP_RE = re.compile(r"/anime/[^/]+/episodio-(\d+)/?$")
DRIVE_ID_RE = re.compile(r"[-\w]{25,}")


def drive_url(src: str) -> str | None:
    """Monta a URL de download do Google Drive a partir do src do iframe."""
    match = DRIVE_ID_RE.search(src or "")
    return f"https://drive.google.com/uc?id={match.group(0)}" if match else None


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
        if host_name == "animexnovel.com":
            return self._info_animexnovel(url)
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
        elif host_name == "animexnovel.com":
            self._download_series(
                url,
                item_ids,
                progress_cb,
                self._info_animexnovel,
                self._episode_animexnovel,
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

    def download_episode(
        self,
        episode_url: str,
        title: str,
        label: str,
        progress_cb: ProgressCb,
    ) -> None:
        """Baixa um episodio avulso (usado pela montagem multi-fonte)."""
        host_name = host(episode_url)
        if host_name == "otakubr.com":
            self._episode_otakubr(episode_url, title, label, progress_cb, ensure_ffmpeg())
        elif host_name == "animesdigital.org":
            self._episode_animesdigital(episode_url, title, label, progress_cb, ensure_ffmpeg())
        elif host_name == "animexnovel.com":
            self._episode_animexnovel(episode_url, title, label, progress_cb)
        else:
            # animeq e qualquer outro site generico: extracao HTML direta
            self._episode_animeq(episode_url, title, label, progress_cb)

    def generic_info(self, url: str, html: str | None = None) -> dict:
        """Enumera episodios de uma pagina de serie em host desconhecido.

        Heuristica: links do mesmo host cujo ultimo segmento parece
        episodio (contem 'episod'/'episode'/'ep' ou termina em numero).
        Aceita HTML pre-renderizado (Playwright) para sites JS.
        """
        if html is None:
            html = fetch(url)
        soup = BeautifulSoup(html, "lxml")
        base_host = urlparse(url).hostname or ""
        items: list[dict] = []
        seen: set[str] = set()
        for link in soup.select("a[href]"):
            href = link.get("href") or ""
            absolute = urljoin(url, href)
            parsed = urlparse(absolute)
            if parsed.hostname != base_host:
                continue
            segmento = (parsed.path or "").rstrip("/").split("/")[-1].lower()
            if not segmento or absolute in seen:
                continue
            parece_ep = (
                "episod" in segmento
                or "episode" in segmento
                or re.search(r"(^|[-_])ep[-_]?\d", segmento)
                or re.search(r"\d+$", segmento)
            )
            if not parece_ep:
                continue
            seen.add(absolute)
            numero = re.findall(r"\d+", segmento)
            label = f"Ep {int(numero[-1]):02d}" if numero else f"Ep {segmento[:20]}"
            if any(item["label"] == label for item in items):
                continue
            items.append({"id": absolute, "label": label})
        if not items:
            raise ScraperError("Nenhum episodio encontrado nesta pagina (host desconhecido).")
        h1 = soup.find("h1")
        return {
            "title": h1.get_text(strip=True) if h1 and h1.get_text(strip=True) else urlparse(url).hostname or "Anime",
            "cover": None,
            "items": items,
        }

    def first_source(self, episode_url: str) -> str | None:
        """Primeira fonte de video resolvivel do episodio (mp4/m3u8), ou None."""
        if host(episode_url) == "animesdigital.org":
            soup = BeautifulSoup(fetch(episode_url), "lxml")
            iframe = soup.select_one('iframe[src*="api.anivideo.net"]')
            if not iframe:
                return None
            src = iframe.get("src") or ""
            return unquote(parse_qs(urlparse(src).query).get("d", [""])[0]) or None
        if host(episode_url) == "animexnovel.com":
            soup = BeautifulSoup(fetch(episode_url), "lxml")
            iframe = soup.select_one('iframe[src*="drive.google.com"]')
            return drive_url(iframe.get("src") or "") if iframe else None
        html = fetch(episode_url, referer=episode_url)
        soup = BeautifulSoup(html, "lxml")
        mp4, m3u8, _ = self._animeq_sources(soup, html, episode_url)
        sources = mp4 + m3u8
        return sources[0] if sources else None

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
        mp4, m3u8, outros = self._animeq_sources(soup, html, url)
        folder = ensure_folder(title)
        target = folder / sanitize(f"{label}.mp4")
        headers = {"User-Agent": USER_AGENT, "Referer": url}
        # 1) mp4 direto (melhor caso)
        for source in mp4:
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
                return
            except httpx.HTTPError:
                continue  # tenta proximo mp4
        # 2) HLS via yt-dlp (melhor qualidade automatica)
        if m3u8:
            ffmpeg = ensure_ffmpeg()
            last_error: Exception | None = None
            for source in m3u8:
                try:
                    ytdlp(source, str(folder / f"{label}.%(ext)s"), progress_cb, ffmpeg)
                    return
                except ScraperError as exc:
                    last_error = exc
            if last_error:
                extra = f" Outros servidores: {', '.join(outros)}." if outros else ""
                raise ScraperError(
                    "Servidores de video deste episodio falharam: "
                    f"{str(last_error)[-100:]}.{extra}"
                ) from last_error
        # 3) so sobraram players protegidos
        tipos = ", ".join(outros) if outros else "nenhum encontrado"
        raise ScraperError(
            "Nenhuma fonte direta disponivel para este episodio "
            f"(servidores restantes: {tipos}). Tente outro anime/host "
            "(ex: animesdigital.org)."
        )

    @staticmethod
    def _animeq_sources(soup: BeautifulSoup, html: str, page: str) -> tuple[list[str], list[str], list[str]]:
        """Classifica as fontes do episodio: (mp4s, m3u8s, players protegidos)."""
        mp4s: list[str] = []
        m3u8s: list[str] = []
        protegidos: set[str] = set()
        for video in soup.select("video"):
            for s in [video.get("src")] + [x.get("src") for x in video.select("source")]:
                src = urljoin(page, s or "")
                if not src:
                    continue
                if ".mp4" in src:
                    mp4s.append(src)
                elif ".m3u8" in src or "stream.php" in src:
                    m3u8s.append(src)
        for found in MP4_RE.findall(html):
            absolute = urljoin(page, found)
            if absolute not in mp4s:
                mp4s.append(absolute)
        for iframe in soup.select("iframe[src]"):
            src = iframe.get("src") or ""
            if "blogger.com" in src:
                protegidos.add("Blogger")
            elif "animeshd.cloud" in src or "strp2p" in src:
                protegidos.add("player FHD (criptografado)")
        return mp4s, m3u8s, sorted(protegidos)

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
        items: list[dict] = []
        for link in soup.select('a[href*="/video/a/"]'):
            href = link.get("href") or ""
            if "#" in href or href in seen:
                continue
            seen.add(href)
            # o numero REAL vem no texto do link ("... Episodio 03 ..."),
            # nao da posicao na lista (site lista do mais novo pro mais velho)
            text = link.get_text(" ", strip=True)
            match = re.search(r"epis[oó]dio\s*(\d+)", text, re.IGNORECASE)
            if match:
                label = f"Ep {int(match.group(1)):02d}"
            else:
                label = f"Ep {text[:30]}" if text else f"item {len(items) + 1}"
            if any(item["label"] == label for item in items):
                continue  # episódio duplicado (multiplos servidores)
            items.append({"id": href, "label": label, "_num": int(match.group(1)) if match else 9999})
        if not items:
            raise ScraperError("Nenhum episodio encontrado nesta pagina.")
        items.sort(key=lambda item: item["_num"])
        for item in items:
            item.pop("_num", None)
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

    # -- animexnovel.com ------------------------------------------------

    def _info_animexnovel(self, url: str) -> dict:
        """Enumera episodios de uma serie do animexnovel (lista carregada por JS)."""
        with browser.run() as context:
            page = context.new_page()
            page.set_default_timeout(30000)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(2000)
                browser.scroll_until_stable(
                    page,
                    "a[href*='episodio']",
                    max_iter=30,
                    wait_ms=800,
                )
                hrefs = page.eval_on_selector_all(
                    "a[href*='episodio']",
                    "els => els.map(e => e.getAttribute('href')).filter(h => h && h.includes('episodio'))",
                )
                title = (page.inner_text("h1") or "").strip()
            except Exception as exc:
                raise ScraperError(f"Falha ao ler a pagina do anime: {exc}") from exc
            finally:
                page.close()
        items: list[dict] = []
        seen: set[str] = set()
        for href in hrefs:
            absolute = urljoin(url, href)
            if absolute.startswith("http://"):
                absolute = "https://" + absolute[len("http://"):]
            if absolute in seen:
                continue
            seen.add(absolute)
            match = ANIMEXNOVEL_EP_RE.search(absolute)
            if not match:
                continue
            items.append({"id": absolute, "label": f"Ep {int(match.group(1)):02d}"})
        if not items:
            raise ScraperError("Nenhum episodio encontrado nesta pagina.")
        return {"title": title or "Anime sem titulo", "cover": None, "items": items}

    def _episode_animexnovel(self, url, title, label, progress_cb) -> None:
        soup = BeautifulSoup(fetch(url), "lxml")
        iframe = soup.select_one('iframe[src*="drive.google.com"]')
        if not iframe:
            raise ScraperError("Nenhuma fonte de video encontrada")
        drive = drive_url(iframe.get("src") or "")
        if not drive:
            raise ScraperError("Nao foi possivel extrair o id do arquivo do Google Drive.")
        folder = ensure_folder(title)
        target = folder / sanitize(f"{label}.mp4")
        import gdown

        progress_cb(0, f"Baixando {label} do Google Drive...")
        try:
            result = gdown.download(
                url=drive,
                output=str(target),
                quiet=True,
            )
        except Exception as exc:  # gdown levanta variados tipos
            raise ScraperError(f"Falha no download do Google Drive: {exc}") from exc
        if not result:
            raise ScraperError(
                "gdown nao conseguiu baixar este episodio (link privado ou cota excedida?)."
            )
