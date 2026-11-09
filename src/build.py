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


def _hora(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone(BRT).strftime("%d/%m %H:%M")


def main() -> None:
    env = Environment(loader=FileSystemLoader(RAIZ / "templates"), autoescape=select_autoescape())
    env.filters["hora"] = _hora
    noticias = _carregar("noticias.json")
    html = env.get_template("index.html").render(noticias=noticias)
    (RAIZ / "docs" / "index.html").write_text(html, encoding="utf-8")
    (RAIZ / "docs" / ".nojekyll").touch()
    print("docs/index.html gerado")


if __name__ == "__main__":
    main()
