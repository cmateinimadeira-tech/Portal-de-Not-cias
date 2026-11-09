"""Coletor RSS/Atom tolerante a falhas: uma fonte quebrada não derruba as outras."""
import calendar
import hashlib
import html
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import feedparser
import requests

UA = "Mozilla/5.0 (compatible; PortalNoticiasPessoal/1.0; +https://github.com/cmateinimadeira-tech/Portal-de-Not-cias)"
MAX_POR_FONTE = 15
MAX_IDADE_H = 72


def _limpar(texto: str, limite: int = 300) -> str:
    texto = re.sub(r"<[^>]+>", " ", texto or "")
    texto = re.sub(r"\s+", " ", html.unescape(texto)).strip()
    return texto if len(texto) <= limite else texto[: limite - 1].rstrip() + "…"


def _data(entry) -> datetime | None:
    for campo in ("published_parsed", "updated_parsed"):
        t = entry.get(campo)
        if t:
            return datetime.fromtimestamp(calendar.timegm(t), tz=timezone.utc)
    return None


def _coletar_fonte(fonte: dict) -> dict:
    try:
        for tentativa in range(3):
            r = requests.get(fonte["url"], headers={"User-Agent": UA}, timeout=20)
            if r.status_code not in (429, 503):
                break
            time.sleep(3 * (tentativa + 1))
        r.raise_for_status()
        feed = feedparser.parse(r.content)
        agora = datetime.now(timezone.utc)
        itens = []
        for e in feed.entries:
            link, titulo = e.get("link"), _limpar(e.get("title", ""), 200)
            if not link or not titulo:
                continue
            d = _data(e) or agora
            if (agora - d).total_seconds() > MAX_IDADE_H * 3600:
                continue
            itens.append({
                "id": hashlib.sha1(link.encode()).hexdigest()[:12],
                "titulo": titulo,
                "resumo": _limpar(e.get("summary", "")),
                "link": link,
                "fonte": fonte["nome"],
                "data": d.isoformat(),
            })
        itens.sort(key=lambda i: i["data"], reverse=True)
        return {"fonte": fonte["nome"], "ok": True, "itens": itens[:MAX_POR_FONTE]}
    except Exception as exc:  # noqa: BLE001
        return {"fonte": fonte["nome"], "ok": False, "erro": str(exc)[:200], "itens": []}


def coletar_aba(fontes: list[dict]) -> tuple[list[dict], list[dict]]:
    with ThreadPoolExecutor(max_workers=6) as ex:
        resultados = list(ex.map(_coletar_fonte, fontes))
    itens = [i for r in resultados for i in r["itens"]]
    itens.sort(key=lambda i: i["data"], reverse=True)
    status = [{k: r[k] for k in ("fonte", "ok", "erro") if k in r} | {"qtd": len(r["itens"])} for r in resultados]
    return itens, status
