"""Testes de parsing do host animefire.app no scraper de animes."""
from app.scrapers.animestream import ANIMEFIRE_EP_RE


def test_regex_episodio_e_temporada():
    match = ANIMEFIRE_EP_RE.search("https://animefire.app/video/monogatari-episodio-3-t2/")
    assert match is not None
    assert int(match.group(1)) == 3  # episodio
    assert int(match.group(2)) == 2  # temporada


def test_regex_rejeita_outros():
    assert ANIMEFIRE_EP_RE.search("https://animefire.app/anime/monogatari/") is None