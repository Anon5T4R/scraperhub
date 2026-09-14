"""Troca de IP para tentar de novo apos um bloqueio por rate-limit.

Opt-in e configuravel em `ip-switch.json` (na raiz do app). Providers:

- ``off``    : desativado (padrao).
- ``warp``   : reconecta o Cloudflare One/WARP via ``warp-cli``.
- ``custom`` : roda um comando do usuario (qualquer VPN/servico com CLI).

A troca NAO burla CAPTCHA: apenas muda o IP de origem quando o site bloqueia
por taxa. O usuario continua resolvendo a verificacao humana quando aparece.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import httpx

from .scrapers.base import ProgressCb, ScraperError, app_root

CONFIG_PATH = app_root() / "ip-switch.json"
DEFAULT_VERIFY_URL = "https://api.ipify.org"
DEFAULT_WAIT_S = 8
WARP_EXE = "warp-cli"
WARP_TIMEOUT_S = 60
CUSTOM_TIMEOUT_S = 120
# Caminhos conhecidos: no exe congelado o PATH pode nao incluir o warp-cli.
WARP_KNOWN_PATHS = (
    Path(r"C:\Program Files\Cloudflare\Cloudflare WARP\warp-cli.exe"),
    Path(r"C:\Program Files (x86)\Cloudflare\Cloudflare WARP\warp-cli.exe"),
)


def _warp_exe() -> str | None:
    """Localiza o warp-cli no PATH ou nos caminhos conhecidos de instalacao."""
    found = shutil.which(WARP_EXE)
    if found:
        return found
    for path in WARP_KNOWN_PATHS:
        if path.is_file():
            return str(path)
    return None


def _default_config() -> dict:
    return {
        "provider": "off",
        "command": "",
        "wait_seconds": DEFAULT_WAIT_S,
        "verify_url": DEFAULT_VERIFY_URL,
        "auto": False,
    }


def load_config() -> dict:
    """Le a config; devolve o padrao se o arquivo faltar/estiver invalido."""
    cfg = _default_config()
    if not CONFIG_PATH.exists():
        return cfg
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return cfg
    if isinstance(data, dict):
        cfg.update({key: data[key] for key in cfg if key in data})
    return cfg


def save_config(data: dict) -> dict:
    """Valida e grava a config; devolve a versao efetiva."""
    cfg = _default_config()
    cfg.update({key: value for key, value in data.items() if key in cfg})
    CONFIG_PATH.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return cfg


def available_providers() -> dict:
    """Quais providers podem rodar nesta maquina."""
    return {"warp": _warp_exe() is not None, "custom": True}


def public_ip(verify_url: str | None = None) -> str | None:
    """IP publico atual (via servico de eco), ou None se nao der para checar."""
    url = verify_url or DEFAULT_VERIFY_URL
    try:
        with httpx.Client(timeout=10, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.text.strip() or None
    except Exception:  # noqa: BLE001 - verificacao nao pode derrubar a troca
        return None


def _run(cmd: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def _switch_warp(progress_cb: ProgressCb) -> str:
    """Reconecta o Cloudflare One/WARP para obter um novo egress."""
    exe = _warp_exe()
    if exe is None:
        raise ScraperError("warp-cli nao encontrado. Instale o Cloudflare One/WARP.")
    progress_cb(10, "Desconectando o WARP...")
    _run([exe, "--accept-tos", "disconnect"])
    time.sleep(3)
    progress_cb(40, "Reconectando o WARP...")
    _run([exe, "--accept-tos", "connect"])
    deadline = time.monotonic() + WARP_TIMEOUT_S
    while time.monotonic() < deadline:
        time.sleep(2)
        output = (_run([exe, "status"]).stdout or "").lower()
        if "connected" in output and "disconnected" not in output:
            return "WARP reconectado"
    raise ScraperError("O WARP nao conectou a tempo.")


def _switch_custom(command: str, progress_cb: ProgressCb) -> str:
    """Roda o comando de troca configurado pelo usuario."""
    if not command.strip():
        raise ScraperError("Nenhum comando de troca de IP configurado.")
    progress_cb(20, "Executando o comando de troca de IP...")
    try:
        proc = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=CUSTOM_TIMEOUT_S
        )
    except subprocess.TimeoutExpired as exc:
        raise ScraperError("O comando de troca de IP demorou demais.") from exc
    if proc.returncode != 0:
        erro = (proc.stderr or proc.stdout or "").strip()[:200]
        raise ScraperError(f"Comando de troca falhou ({proc.returncode}): {erro}")
    return "comando executado"


def switch_ip(progress_cb: ProgressCb, config: dict | None = None) -> dict:
    """Executa a troca conforme a config e relata o IP antes/depois."""
    cfg = config or load_config()
    provider = str(cfg.get("provider") or "off")
    if provider == "off":
        raise ScraperError("Troca de IP desativada (provider=off em ip-switch.json).")

    before = public_ip(cfg.get("verify_url"))
    progress_cb(5, f"IP atual: {before or 'desconhecido'}")

    if provider == "warp":
        detail = _switch_warp(progress_cb)
    elif provider == "custom":
        detail = _switch_custom(str(cfg.get("command") or ""), progress_cb)
    else:
        raise ScraperError(f"Provider desconhecido: {provider}")

    wait = int(cfg.get("wait_seconds") or DEFAULT_WAIT_S)
    progress_cb(80, f"Aguardando {wait}s para a rede estabilizar...")
    time.sleep(max(0, wait))
    after = public_ip(cfg.get("verify_url"))
    changed = bool(before and after and before != after)
    sufixo = "" if changed else " (nao mudou — o servico pode estar reusando o mesmo IP)"
    progress_cb(100, f"IP agora: {after or 'desconhecido'}{sufixo}")
    return {
        "provider": provider,
        "ip_before": before,
        "ip_after": after,
        "changed": changed,
        "detail": detail,
    }
