"""Cliente mínimo da API do Gemini (REST). A chave vem só da variável de ambiente.

Tenta os modelos em ordem; se um deles estourar o tempo, passa para o próximo
(mais leve) pelo resto da execução. Registra no log quanto cada chamada levou.
"""
import json
import os
import time

import requests

BASE = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"
MODELOS = os.environ.get("GEMINI_MODELS", "gemini-flash-lite-latest,gemini-flash-latest").split(",")
TIMEOUT_S = 90


class GeminiIndisponivel(Exception):
    pass


def disponivel() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


_modelo_idx = 0
_pensamento_ok = True  # desliga o "thinkingConfig" se o modelo não aceitar


_esquema_ok = True  # desliga o "responseSchema" se o modelo não aceitar


def _chamar(prompt: str, timeout: int, esquema: dict | None) -> requests.Response:
    config = {"responseMimeType": "application/json", "temperature": 0.2, "maxOutputTokens": 16000}
    if esquema and _esquema_ok:
        config["responseSchema"] = esquema  # força o formato: evita JSON quebrado ou fora do padrão
    if _pensamento_ok:
        config["thinkingConfig"] = {"thinkingLevel": "low"}
    corpo = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": config}
    return requests.post(BASE.format(MODELOS[_modelo_idx].strip()), json=corpo,
                         headers={"X-goog-api-key": os.environ["GEMINI_API_KEY"]}, timeout=timeout)


def gerar_json(prompt: str, tentativas: int = 3, timeout: int = TIMEOUT_S, esquema: dict | None = None):
    global _modelo_idx, _pensamento_ok, _esquema_ok
    if not disponivel():
        raise GeminiIndisponivel("GEMINI_API_KEY ausente")
    ultimo = ""
    for t in range(tentativas):
        modelo = MODELOS[_modelo_idx].strip()
        inicio = time.monotonic()
        try:
            r = _chamar(prompt, timeout, esquema)
        except requests.RequestException as exc:
            ultimo = f"{modelo}: {type(exc).__name__} após {time.monotonic() - inicio:.0f}s"
            print("  " + ultimo, flush=True)
            if _modelo_idx + 1 < len(MODELOS):
                _modelo_idx += 1  # modelo lento: troca pelo mais leve até o fim da execução
            continue
        dur = time.monotonic() - inicio
        if r.status_code == 400 and _pensamento_ok and "thinking" in r.text.lower():
            _pensamento_ok = False
            continue
        if r.status_code == 400 and _esquema_ok and "schema" in r.text.lower():
            print(f"  {modelo}: esquema recusado, seguindo sem ele", flush=True)
            _esquema_ok = False
            continue
        if r.status_code != 200:
            ultimo = f"{modelo}: HTTP {r.status_code} após {dur:.0f}s: {r.text[:200]}"  # nunca inclui a chave
            print("  " + ultimo, flush=True)
            if r.status_code in (429, 500, 503):
                time.sleep(10 * (t + 1))
                continue
            if r.status_code == 404 and _modelo_idx + 1 < len(MODELOS):
                _modelo_idx += 1
                continue
            raise GeminiIndisponivel(ultimo)
        try:
            texto = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            res = json.loads(texto)
            print(f"  {modelo}: ok em {dur:.0f}s", flush=True)
            return res
        except (KeyError, IndexError, ValueError) as exc:
            ultimo = f"{modelo}: resposta inválida ({exc})"
            print("  " + ultimo, flush=True)
    raise GeminiIndisponivel(ultimo or "falha desconhecida")


def testar() -> bool:
    """Chamada mínima para saber se a API responde antes de gastar minutos."""
    try:
        gerar_json('Responda exatamente {"ok": true}', tentativas=len(MODELOS) + 1, timeout=45)
        return True
    except GeminiIndisponivel as exc:
        print(f"Teste do Gemini falhou: {exc}", flush=True)
        return False
