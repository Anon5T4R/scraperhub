"""Descoberta de novas fontes de anime via busca web (DuckDuckGo HTML)."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, quote_plus, urlparse

import httpx
from bs4 import BeautifulSoup

from .scrapers.animestream_net import USER_AGENT

DDG_URL = "https://html.duckduckgo.com/html/"
# hosts que nunca sao fonte de episodio baixavel
BLOCKLIST = (
    "youtube.com", "youtu.be", "reddit.com", "myanimelist.net", "anilist.co",
    "facebook.com", "twitter.com", "x.com", "instagram.com", "wikipedia.org",
    "crunchyroll.com", "netflix.com", "primevideo.com", "disneyplus.com",
    "hbo.com", "max.com", "tiktok.com", "pinterest.com", "amazon.com",
    "google.com", "bing.com", "duckduckgo.com", "globo.com", "viz.com",
)
ANIME_PATH_RE = re.compile(r"^/anime/(?:a/)?[^/]+", re.IGNORECASE)
MAX_HOSTS = 6


def _ddg_results(term: str) -> list[str]:
    """URLs de resultado da busca HTML do DuckDuckGo."""
    try:
        response = httpx.get(
            DDG_URL,
            params={"q": f"{term} anime episodio online assistir"},
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            timeout=20,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        return []
    soup = BeautifulSoup(response.text, "lxml")
    urls: list[str] = []
    for link in soup.select("a.result__a, a.result__url"):
        href = link.get("href") or ""
        # resultados vao como /l/?uddg=<url codificada>
        if "uddg=" in href:
            decoded = parse_qs(urlparse(href).query).get("uddg", [""])[0]
            if decoded:
                urls.append(decoded)
        elif href.startswith("http"):
            urls.append(href)
    return urls


def _host_ok(url: str, conhecidos: set[str]) -> bool:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if not host or host in conhecidos:
        return False
    return not any(host == b or host.endswith("." + b) for b in BLOCKLIST)


def relevante(texto: str, term: str) -> bool:
    """Todos os tokens do termo (ou a juncao deles) aparecem no texto?"""
    tokens = [t for t in re.split(r"\W+", term.lower()) if len(t) >= 2]
    if not tokens:
        return True
    alvo = texto.lower()
    juntado = "".join(tokens)
    return all(t in alvo for t in tokens) or juntado in alvo.replace(" ", "").replace("-", "")


def discover_sites(term: str, conhecidos: list[str]) -> list[dict]:
    """Busca na web sites novos com o anime; valida busca ?s= antes de aceitar.

    Retorna [{site, url}] onde url e a pagina da serie encontrada.
    """
    conhecidos_set = {(urlparse(u).hostname or "").removeprefix("www.") for u in conhecidos}
    candidatos: list[str] = []
    for url in _ddg_results(term):
        if not _host_ok(url, conhecidos_set):
            continue
        parsed = urlparse(url)
        if not ANIME_PATH_RE.match(parsed.path or ""):
            continue  # so paginas de serie nos interessam
        host = (parsed.hostname or "").removeprefix("www.")
        entry = f"https://{host}{parsed.path}"
        if entry not in candidatos:
            candidatos.append(entry)
        if len(candidatos) >= MAX_HOSTS:
            break
    achados: list[dict] = []
    for entry in candidatos:
        host = urlparse(entry).hostname or ""
        try:
            response = httpx.get(
                entry,
                headers={"User-Agent": USER_AGENT},
                follow_redirects=True,
                timeout=15,
            )
            response.raise_for_status()
        except httpx.HTTPError:
            continue
        soup = BeautifulSoup(response.text, "lxml")
        title = soup.select_one("h1")
        # rigor: h1 E url final precisam bater com o termo (alguns sites
        # quebrados mostram h1 de outro anime na pagina)
        h1_texto = title.get_text(" ", strip=True) if title else ""
        if not (relevante(h1_texto, term) and relevante(str(response.url), term)):
            continue
        achados.append({"site": host, "url": str(response.url)})
        if len(achados) >= 3:
            break
    return achados
