"""Renderiza docs/index.html a partir de data/*.json."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

RAIZ = Path(__file__).resolve().parent.parent
BRT = timezone(timedelta(hours=-3))


def _carregar(nome: str) -> dict:
    p = RAIZ / "data" / nome
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


DIAS = "seg ter qua qui sex sáb dom".split()


def _hora(iso: str) -> str:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(BRT).strftime("%d/%m %H:%M")


def _quando(iso: str) -> str:
    """Data de jogo em Brasília: 'hoje 21:30', 'amanhã 16:00' ou 'sáb 22/11 16:30'."""
    d = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(BRT)
    delta = (d.date() - datetime.now(BRT).date()).days
    dia = {0: "hoje", 1: "amanhã", -1: "ontem"}.get(delta, f"{DIAS[d.weekday()]} {d:%d/%m}")
    return f"{dia} {d:%H:%M}"


MESES = "jan fev mar abr mai jun jul ago set out nov dez".split()


def _num(v, casas: int = 2) -> str:
    if v is None:
        return "–"
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _data(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%d/%m/%Y") if iso else ""


def _mes(iso: str) -> str:
    d = datetime.fromisoformat(iso)
    return f"{MESES[d.month - 1]}/{d.year}"


def _seta(atual, antes) -> str:
    if atual is None or antes is None or abs(atual - antes) < 1e-9:
        return "="
    return "▲" if atual > antes else "▼"


def main() -> None:
    env = Environment(loader=FileSystemLoader(RAIZ / "templates"), autoescape=select_autoescape())
    env.filters.update(hora=_hora, quando=_quando, num=_num, data=_data, mes=_mes)
    env.globals["seta"] = _seta
    noticias = _carregar("noticias.json")
    html = env.get_template("index.html").render(noticias=noticias, bcb=_carregar("bcb.json"),
                                                  futebol=_carregar("futebol.json"))
    (RAIZ / "docs" / "index.html").write_text(html, encoding="utf-8")
    (RAIZ / "docs" / ".nojekyll").touch()
    print("docs/index.html gerado")


if __name__ == "__main__":
    main()
