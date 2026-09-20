"""Testes de idioma e persistencia de sites de busca."""
from app.search import LANGUAGE_PADRAO, _idioma, load_sites, save_sites


def test_idioma_dublado():
    assert _idioma("naruto dublado ep 1") == "Dublado"


def test_idioma_legendado_padrao():
    assert _idioma("naruto legendado ep 1") == LANGUAGE_PADRAO


def test_idioma_case_insensitive():
    assert _idioma("NARUTO DUBLADO") == "Dublado"


def test_idioma_vazio():
    assert _idioma("") == LANGUAGE_PADRAO


def test_save_sites_normaliza_e_deduplica(tmp_path, monkeypatch):
    arquivo = tmp_path / "sites.txt"
    monkeypatch.setattr("app.search.SITES_FILE", arquivo)
    salvas = save_sites(["https://animeq.cloud/", "animeq.cloud", "http://AnimeQ.Cloud/path/"])
    assert salvas == ["https://animeq.cloud/", "http://animeq.cloud/path/"]
    assert arquivo.read_text(encoding="utf-8") == (
        "https://animeq.cloud/\nhttp://animeq.cloud/path/\n"
    )


def test_save_sites_ignora_invalidos(tmp_path, monkeypatch):
    arquivo = tmp_path / "sites.txt"
    monkeypatch.setattr("app.search.SITES_FILE", arquivo)
    assert save_sites(["", "# comentario", "ftp://x.com"]) == []
    assert arquivo.read_text(encoding="utf-8") == "\n"


def test_load_sites_le_arquivo(tmp_path, monkeypatch):
    arquivo = tmp_path / "sites.txt"
    arquivo.write_text(
        "# comentario\nhttps://animeq.cloud/\n\nhttps://animesdigital.org/\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("app.search.SITES_FILE", arquivo)
    assert load_sites() == ["https://animeq.cloud/", "https://animesdigital.org/"]


def test_load_sites_cria_com_defaults(tmp_path, monkeypatch):
    arquivo = tmp_path / "sites.txt"
    monkeypatch.setattr("app.search.SITES_FILE", arquivo)
    assert load_sites() == [
        "https://animeq.cloud/",
        "https://animesdigital.org/",
        "https://animefire.app/",
    ]
    assert arquivo.exists()
