"""Testes de normalize_url: validacao de scheme e hostname."""
import pytest

from app.scrapers import normalize_url


def test_sem_scheme_ganha_https():
    assert normalize_url("animeq.cloud") == "https://animeq.cloud"


def test_com_scheme_preservado():
    assert normalize_url("http://animeq.cloud/") == "http://animeq.cloud/"


def test_trim_antes_do_prefixo():
    assert normalize_url("  animeq.cloud  ") == "https://animeq.cloud"


def test_scheme_maiusculo_aceito():
    assert normalize_url("HTTPS://AnimeQ.Cloud/") == "HTTPS://AnimeQ.Cloud/"


@pytest.mark.parametrize(
    "url",
    ["", "foo bar", "http://", "::::", "https://", "ftp://animeq.cloud"],
)
def test_invalidas_levantam_valueerror(url):
    with pytest.raises(ValueError):
        normalize_url(url)