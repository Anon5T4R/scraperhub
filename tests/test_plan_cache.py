"""Testes do cache de planos de montagem (o plano aprovado e o plano baixado)."""
import app.main as main


def _chave(term: str = "Naruto", full: bool = False) -> str:
    return main._plan_key(term, "qualquer", full)


def test_roundtrip():
    key = _chave()
    plan = {"fontes": [], "episodios": []}
    main._store_plan(key, plan)
    assert main._cached_plan(key) == plan


def test_miss():
    assert main._cached_plan(_chave("Inexistente")) is None


def test_chave_diferencia_full():
    assert _chave() != _chave(full=True)


def test_expira_apos_ttl(monkeypatch):
    key = _chave("Velho", full=True)
    main._store_plan(key, {"episodios": [1]})
    agora = main.time.monotonic()
    monkeypatch.setattr(main.time, "monotonic", lambda: agora + main.PLAN_TTL_S + 1)
    assert main._cached_plan(key) is None
