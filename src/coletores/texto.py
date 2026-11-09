"""Extrai o texto principal de uma matéria, só a partir do HTML que o site entrega
publicamente (sem contornar paywall). O texto serve apenas de insumo para o resumo
da IA: não é publicado nem gravado no repositório.
"""
from concurrent.futures import ThreadPoolExecutor

import requests
import trafilatura

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
SEM_EXTRACAO = ("news.google.com", "reddit.com")  # redirecionamento por JS / conteúdo já no RSS
MAX_CHARS = 2500


def extrair(url: str) -> str:
    if any(d in url for d in SEM_EXTRACAO):
        return ""
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=15)
        if r.status_code != 200:
            return ""
        texto = trafilatura.extract(r.content, include_comments=False, include_tables=False,
                                    favor_precision=True) or ""
    except Exception:  # noqa: BLE001
        return ""
    return texto[:MAX_CHARS]


def extrair_varios(urls: list[str]) -> dict[str, str]:
    with ThreadPoolExecutor(max_workers=8) as ex:
        return dict(zip(urls, ex.map(extrair, urls)))
