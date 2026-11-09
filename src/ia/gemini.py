"""Cliente mínimo da API do Gemini (REST). A chave vem só da variável de ambiente."""
import json
import os
import time

import requests

MODELO = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent"


class GeminiIndisponivel(Exception):
    pass


def disponivel() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


_pensamento_ok = True  # desliga o "thinkingConfig" se o modelo não aceitar


def gerar_json(prompt: str, tentativas: int = 2) -> dict:
    global _pensamento_ok
    chave = os.environ.get("GEMINI_API_KEY")
    if not chave:
        raise GeminiIndisponivel("GEMINI_API_KEY ausente")
    ultimo = ""
    for t in range(tentativas + 1):
        config = {"responseMimeType": "application/json", "temperature": 0.2, "maxOutputTokens": 12000}
        if _pensamento_ok:
            # pensamento mínimo: tarefa simples, resposta bem mais rápida
            config["thinkingConfig"] = {"thinkingLevel": "low"}
        corpo = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": config}
        try:
            r = requests.post(URL, json=corpo, headers={"X-goog-api-key": chave}, timeout=150)
        except requests.RequestException as exc:
            ultimo = f"{type(exc).__name__}"
            continue
        if r.status_code == 400 and _pensamento_ok and "thinking" in r.text.lower():
            _pensamento_ok = False
            continue
        if r.status_code in (429, 500, 503):
            ultimo = f"HTTP {r.status_code}"
            time.sleep(10 * (t + 1))
            continue
        if r.status_code != 200:
            # nunca inclui a chave na mensagem
            raise GeminiIndisponivel(f"HTTP {r.status_code}: {r.text[:200]}")
        try:
            texto = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(texto)
        except (KeyError, IndexError, ValueError) as exc:
            ultimo = f"resposta inválida: {exc}"
    raise GeminiIndisponivel(ultimo or "falha desconhecida")
