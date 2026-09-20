"""Testes do filtro de relevancia da descoberta de fontes."""
from app.discovery import relevante


def test_tokens_presentes():
    assert relevante("One Piece ep 1 online", "one piece")


def test_tokens_ausentes():
    assert not relevante("Naruto ep 1 online", "one piece")


def test_juncao_sem_espaco():
    assert relevante("onepiece ep 1", "one piece")


def test_juncao_com_hifen():
    assert relevante("one-piece ep 1", "one piece")


def test_case_insensitive():
    assert relevante("ONE PIECE EP 1", "one piece")


def test_termo_sem_tokens():
    assert relevante("qualquer coisa", "a b")
