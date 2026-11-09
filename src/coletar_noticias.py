"""Lê config/feeds.yml, coleta todas as abas e grava data/noticias.json."""
import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

from src.coletores.rss import coletar_aba

RAIZ = Path(__file__).resolve().parent.parent


def main() -> None:
    cfg = yaml.safe_load((RAIZ / "config" / "feeds.yml").read_text(encoding="utf-8"))
    saida = {"atualizado_em": datetime.now(timezone.utc).isoformat(), "abas": {}}
    for chave, aba in cfg["abas"].items():
        itens, status = coletar_aba(aba["fontes"])
        saida["abas"][chave] = {"titulo": aba["titulo"], "itens": itens, "status": status}
        falhas = [s["fonte"] for s in status if not s["ok"]]
        print(f"{chave}: {len(itens)} itens" + (f" | falhas: {', '.join(falhas)}" if falhas else ""))
    (RAIZ / "data" / "noticias.json").write_text(json.dumps(saida, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
