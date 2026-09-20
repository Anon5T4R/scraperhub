"""Testes das funcoes de rotulo e qualidade da montagem de temporada."""
import pytest

from app.assembly import (
    _canonical,
    _label_key,
    _label_num,
    _quality_score,
    download_season,
)
from app.scrapers.base import ScraperError


def test_label_num():
    assert _label_num("Ep 03") == 3
    assert _label_num("S1E03") == 3
    assert _label_num("Ep 12") == 12


def test_label_num_sem_numero():
    assert _label_num("Ep trailer") is None
    assert _label_num("") is None


def test_canonical():
    assert _canonical("Ep 03") == "Ep 03"
    assert _canonical("S1E03") == "Ep 03"
    assert _canonical("Ep 3") == "Ep 03"


def test_canonical_sem_numero():
    assert _canonical("Ep trailer") == "ep trailer"


def test_label_key():
    assert _label_key("Ep 03") == (0, 3, "Ep 03")
    assert _label_key("S1E03") == (0, 3, "S1E03")


def test_label_key_sem_numero_por_ultimo():
    assert _label_key("Ep trailer") == (1, 0, "Ep trailer")


def test_quality_score():
    assert _quality_score("1080p") == 1080
    assert _quality_score("720p") == 720
    assert _quality_score("unica") == 1
    assert _quality_score("desconhecida") == 0


def test_quality_score_none():
    assert _quality_score(None) == -1
    assert _quality_score("") == -1


def test_download_season_usa_plano_precomputado():
    """Plano fornecido nao deve disparar busca na web (episodios vazios -> erro imediato)."""
    plan = {"fontes": [], "episodios": []}
    with pytest.raises(ScraperError):
        download_season(
            "qualquer-coisa", "qualquer", None, lambda progress, message: None, plan=plan
        )
