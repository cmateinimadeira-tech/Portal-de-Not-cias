"""Futebol: tabelas e jogos (football-data.org) e destaque do Flamengo (ESPN).

Modos:
  python -m src.coletores.futebol diario    -> tabelas + jogos de -3 a +7 dias + destaque
  python -m src.coletores.futebol placares  -> só atualiza placares, e só se houver jogo agora

A chave FOOTBALL_DATA_KEY vem do ambiente (GitHub Secret). O plano gratuito permite
10 requisições por minuto: o cliente lê os cabeçalhos de limite e espera quando precisa.
Grava data/futebol.json.
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import yaml

RAIZ = Path(__file__).resolve().parent.parent.parent
API = "https://api.football-data.org/v4"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer/{liga}/teams/{time}/schedule"
ARQ = RAIZ / "data" / "futebol.json"


# ---------- football-data.org ----------

def _fd(caminho: str, params: dict | None = None) -> dict:
    chave = os.environ.get("FOOTBALL_DATA_KEY")
    if not chave:
        raise RuntimeError("FOOTBALL_DATA_KEY ausente")
    for _ in range(3):
        r = requests.get(f"{API}{caminho}", params=params, headers={"X-Auth-Token": chave}, timeout=30)
        if r.status_code == 429:  # estourou o limite por minuto
            espera = int(r.headers.get("X-RequestCounter-Reset", "60")) + 1
            print(f"  limite atingido, aguardando {espera}s", flush=True)
            time.sleep(espera)
            continue
        r.raise_for_status()
        # throttling preventivo pelos cabeçalhos da API
        if int(r.headers.get("X-Requests-Available-Minute", "10")) <= 1:
            time.sleep(int(r.headers.get("X-RequestCounter-Reset", "60")) + 1)
        return r.json()
    raise RuntimeError(f"limite de requisições persistente em {caminho}")


def _time(t: dict) -> dict:
    return {"id": t.get("id"), "nome": t.get("shortName") or t.get("name") or "?", "sigla": t.get("tla"),
            "escudo": t.get("crest")}


def _jogo(m: dict) -> dict:
    ft = (m.get("score") or {}).get("fullTime") or {}
    return {"id": m["id"], "data": m["utcDate"], "status": m["status"], "rodada": m.get("matchday"),
            "fase": m.get("stage"), "casa": _time(m["homeTeam"]), "fora": _time(m["awayTeam"]),
            "gols_casa": ft.get("home"), "gols_fora": ft.get("away"),
            "liga": (m.get("competition") or {}).get("code")}


def _tabela(dados: dict) -> list[dict]:
    tabelas = [s for s in dados.get("standings", []) if s.get("type") == "TOTAL"]
    saida = []
    for s in tabelas:
        saida.append({"grupo": s.get("group"), "linhas": [{
            "pos": l["position"], "time": _time(l["team"]), "pj": l["playedGames"], "v": l["won"],
            "e": l["draw"], "d": l["lost"], "sg": l["goalDifference"], "pts": l["points"],
        } for l in s.get("table", [])]})
    return saida


# ---------- ESPN (time em destaque) ----------

def _espn_eventos(liga: str, espn_id: int, futuros: bool) -> list[dict]:
    r = requests.get(ESPN.format(liga=liga, time=espn_id), params={"fixture": "true"} if futuros else None,
                     timeout=20)
    if r.status_code != 200:
        return []
    saida = []
    for e in r.json().get("events", []):
        c = e["competitions"][0]
        st = c.get("status", {}).get("type", {})
        lados = {t["homeAway"]: t for t in c.get("competitors", [])}
        if "home" not in lados or "away" not in lados:
            continue

        def lado(t):
            logos = t["team"].get("logos") or [{}]
            placar = t.get("score")
            gols = placar.get("displayValue") if isinstance(placar, dict) else placar
            return {"nome": t["team"].get("shortDisplayName") or t["team"].get("displayName"),
                    "escudo": logos[0].get("href"), "gols": gols}
        saida.append({"id": e["id"], "data": e["date"], "competicao": (e.get("league") or {}).get("name", liga),
                      "estado": st.get("state"), "detalhe": st.get("shortDetail"),
                      "local": (c.get("venue") or {}).get("fullName"),
                      "casa": lado(lados["home"]), "fora": lado(lados["away"])})
    return saida


TRADUZ_COMP = {"Brazilian Serie A": "Brasileirão", "CONMEBOL Libertadores": "Libertadores",
               "Copa do Brasil": "Copa do Brasil", "Brazilian Copa do Brasil": "Copa do Brasil"}


def destaque(cfg: dict) -> dict:
    futuros, passados = {}, {}
    for liga in cfg["espn_ligas"]:
        for e in _espn_eventos(liga, cfg["espn_id"], futuros=True):
            futuros[e["id"]] = e
        for e in _espn_eventos(liga, cfg["espn_id"], futuros=False):
            if e["estado"] == "post":
                passados[e["id"]] = e
    for e in [*futuros.values(), *passados.values()]:
        e["competicao"] = TRADUZ_COMP.get(e["competicao"], e["competicao"])
    proximos = sorted(futuros.values(), key=lambda e: e["data"])[:6]
    ultimos = sorted(passados.values(), key=lambda e: e["data"], reverse=True)[:5]
    return {"nome": cfg["nome"], "proximos": proximos, "ultimos": ultimos}


# ---------- modos ----------

def _ler() -> dict:
    return json.loads(ARQ.read_text(encoding="utf-8")) if ARQ.exists() else {"ligas": {}}


def _gravar(dados: dict) -> None:
    dados["atualizado_em"] = datetime.now(timezone.utc).isoformat()
    ARQ.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")


def diario(cfg: dict) -> None:
    dados = _ler()
    codigos = [l["codigo"] for l in cfg["ligas"]]
    hoje = datetime.now(timezone.utc).date()
    for liga in cfg["ligas"]:
        try:
            d = dados["ligas"].setdefault(liga["codigo"], {})
            d["nome"] = liga["nome"]
            d["tabela"] = _tabela(_fd(f"/competitions/{liga['codigo']}/standings"))
            print(f"{liga['codigo']}: tabela ok", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"{liga['codigo']}: tabela falhou ({exc}); mantendo anterior", flush=True)
    try:  # uma única requisição para os jogos de todas as ligas (janela máx. de 10 dias)
        jogos = _fd("/matches", {"competitions": ",".join(codigos),
                                 "dateFrom": (hoje - timedelta(days=3)).isoformat(),
                                 "dateTo": (hoje + timedelta(days=6)).isoformat()})["matches"]
        for c in codigos:
            dados["ligas"].setdefault(c, {})["jogos"] = sorted(
                (_jogo(m) for m in jogos if (m.get("competition") or {}).get("code") == c), key=lambda j: j["data"])
        print(f"jogos: {len(jogos)}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"jogos falharam ({exc}); mantendo anteriores", flush=True)
    try:
        dados["destaque"] = destaque(cfg["destaque"])
        print(f"destaque: {len(dados['destaque']['proximos'])} próximos jogos", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"destaque falhou ({exc})", flush=True)
    _gravar(dados)


def ha_jogo_agora(dados: dict, agora: datetime) -> bool:
    """Há jogo começando em até 15 min ou que começou há menos de 2h30?"""
    inicios = [datetime.fromisoformat(j["data"].replace("Z", "+00:00"))
               for liga in dados.get("ligas", {}).values() for j in liga.get("jogos", [])]
    inicios += [datetime.fromisoformat(e["data"].replace("Z", "+00:00"))
                for e in (dados.get("destaque") or {}).get("proximos", [])]
    return any(-timedelta(minutes=15) <= agora - i <= timedelta(hours=2, minutes=30) for i in inicios)


def placares(cfg: dict) -> None:
    dados = _ler()
    agora = datetime.now(timezone.utc)
    if not ha_jogo_agora(dados, agora):
        print("nenhum jogo em andamento: nada a fazer")
        return
    codigos = [l["codigo"] for l in cfg["ligas"]]
    jogos = _fd("/matches", {"competitions": ",".join(codigos),
                             "dateFrom": (agora - timedelta(days=1)).date().isoformat(),
                             "dateTo": (agora + timedelta(days=1)).date().isoformat()})["matches"]
    novos = {m["id"]: _jogo(m) for m in jogos}
    for liga in dados.get("ligas", {}).values():
        liga["jogos"] = [novos.get(j["id"], j) for j in liga.get("jogos", [])]
    print(f"placares: {len(novos)} jogos atualizados", flush=True)
    try:
        dados["destaque"] = destaque(cfg["destaque"])
    except Exception as exc:  # noqa: BLE001
        print(f"destaque falhou ({exc})", flush=True)
    _gravar(dados)


def main() -> None:
    cfg = yaml.safe_load((RAIZ / "config" / "ligas.yml").read_text(encoding="utf-8"))
    modo = sys.argv[1] if len(sys.argv) > 1 else "diario"
    {"diario": diario, "placares": placares}[modo](cfg)


if __name__ == "__main__":
    main()
