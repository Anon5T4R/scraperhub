"""Testes do scraper de manga por pagina de serie (asurascans)."""
from app.scrapers import detect, get_scraper
from app.scrapers.seriesmanga import SERIES_PATH_RE, SeriesMangaScraper

SERIE = "https://asurascans.com/comics/surviving-the-game-as-a-barbarian-53fc8424"

SERIES_HTML = f"""
<html><body><main>
<h1>Surviving The Game as a Barbarian</h1>
<meta property="og:image" content="https://cdn.asurascans.com/capa.webp">
<img src="https://cdn.asurascans.com/asura-images/covers/capa.webp">
<a href="/comics/surviving-the-game-as-a-barbarian-53fc8424/chapter/160">Cap 160</a>
<a href="/comics/surviving-the-game-as-a-barbarian-53fc8424/chapter/2">Cap 2</a>
<a href="/comics/surviving-the-game-as-a-barbarian-53fc8424/chapter/1">Cap 1</a>
<a href="/comics/surviving-the-game-as-a-barbarian-53fc8424/chapter/159.5">Cap 159.5</a>
<a href="/comics/outra-serie/chapter/3">outra serie</a>
<a href="https://asurascans.com/comics/surviving-the-game-as-a-barbarian-53fc8424/chapter/2">duplicado</a>
</main></body></html>
"""

CHAPTER_HTML = """
<html><body><main>
<img src="https://cdn.asurascans.com/asura-images/covers/capa.webp">
<img src="https://cdn.asurascans.com/asura-images/banners/banner.webp">
<img src="https://cdn.asurascans.com/asura-images/chapters/serie/1/001.webp">
<img data-src="https://cdn.asurascans.com/asura-images/chapters/serie/1/002.webp">
<img src="https://cdn.asurascans.com/asura-images/chapters/serie/1/001.webp">
</main></body></html>
"""


def test_match():
    scraper = SeriesMangaScraper()
    assert scraper.match(SERIE)
    assert scraper.match(SERIE + "/chapter/5")
    assert not scraper.match("https://mangahub.io/manga/onepunch-man")
    assert not scraper.match("https://google.com/comics/x")


def test_detect_registrado():
    scraper = detect(SERIE)
    assert scraper is not None and scraper.id == "seriesmanga"
    assert get_scraper("seriesmanga") is not None


def test_series_path_re():
    assert SERIES_PATH_RE.match("/comics/slug")
    assert not SERIES_PATH_RE.match("/comics/slug/chapter/1")
    assert not SERIES_PATH_RE.match("/manga/slug")


def test_series_url_normaliza_capitulo():
    assert (
        SeriesMangaScraper._series_url(SERIE + "/chapter/12")
        == SERIE
    )


def test_get_info_lista_e_ordena(monkeypatch):
    scraper = SeriesMangaScraper()

    class FakeResponse:
        text = SERIES_HTML
        status_code = 200
        url = SERIE

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            return None

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def get(self, url: str, headers=None):
            return FakeResponse()

    monkeypatch.setattr("app.scrapers.seriesmanga.httpx.Client", FakeClient)
    info = scraper.get_info(SERIE)
    labels = [i["label"] for i in info["items"]]
    # mais novo primeiro, com decimal no lugar certo; duplicado e outra serie fora
    assert labels == ["Cap. 160", "Cap. 159.5", "Cap. 2", "Cap. 1"]
    assert info["title"] == "Surviving The Game as a Barbarian"
    assert info["cover"].endswith("capa.webp")


def test_chapter_images_filtra_capa_e_banner():
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(CHAPTER_HTML, "lxml")
    urls = SeriesMangaScraper._chapter_images(soup, "/chapters/")
    assert urls == [
        "https://cdn.asurascans.com/asura-images/chapters/serie/1/001.webp",
        "https://cdn.asurascans.com/asura-images/chapters/serie/1/002.webp",
    ]
