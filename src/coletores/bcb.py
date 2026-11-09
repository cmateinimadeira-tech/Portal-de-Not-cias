"""Indicadores do Banco Central: Selic, IPCA, dólar (SGS) e expectativas do Focus (Olinda).

Grava data/bcb.json. APIs públicas, sem chave. Se uma série falhar, as demais seguem
e o valor anterior (do último data/bcb.json) é mantido.
"""
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import requests

RAIZ = Path(__file__).resolve().parent.parent.parent
SGS = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{}/dados/ultimos/{}?formato=json"  # máx. 20 pontos
SGS_PERIODO = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{}/dados?formato=json&dataInicial={}&dataFinal={}"
FOCUS = ("https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/ExpectativasMercadoAnuais"
         "?$top={top}&$filter={filtro}&$orderby=Data%20desc&$select=Data,DataReferencia,Mediana&$format=json")
FONTE_SGS = "https://www3.bcb.gov.br/sgspub/"
FONTE_FOCUS = "https://www.bcb.gov.br/publicacoes/focus"


def _get(url: str):
    r = requests.get(url, timeout=40, headers={"Accept": "application/json"})
    r.raise_for_status()
    return r.json()


def _serie(codigo: int, n: int = 0, dias: int = 0) -> list[tuple[date, float]]:
    hoje = date.today()
    if dias:
        url = SGS_PERIODO.format(codigo, (hoje - timedelta(days=dias)).strftime("%d/%m/%Y"), hoje.strftime("%d/%m/%Y"))
    else:
        url = SGS.format(codigo, n)
    pontos = [(datetime.strptime(p["data"], "%d/%m/%Y").date(), float(p["valor"])) for p in _get(url)]
    return [p for p in pontos if p[0] <= hoje]  # a série da meta Selic vem preenchida até a próxima reunião


def selic() -> dict:
    pontos = _serie(432, dias=730)
    atual = pontos[-1][1]
    anterior, desde = None, pontos[0][0]
    for d, v in reversed(pontos):
        if v != atual:
            anterior = v
            break
        desde = d
    return {"valor": atual, "anterior": anterior, "desde": desde.isoformat(),
            "rotulo": "Selic (meta)", "unidade": "% a.a.", "fonte": FONTE_SGS}


def ipca() -> dict:
    mensal = _serie(433, 3)
    acum = _serie(13522, 2)
    return {"mes": mensal[-1][0].isoformat(), "mensal": mensal[-1][1], "mensal_anterior": mensal[-2][1],
            "acum12": acum[-1][1], "acum12_anterior": acum[-2][1],
            "rotulo": "IPCA", "fonte": FONTE_SGS}


def dolar() -> dict:
    pontos = _serie(1, 5)
    return {"valor": pontos[-1][1], "anterior": pontos[-2][1], "data": pontos[-1][0].isoformat(),
            "rotulo": "Dólar (PTAX venda)", "fonte": FONTE_SGS}


FOCUS_INDICADORES = [("IPCA", "IPCA", "%"), ("Selic", "Selic fim de ano", "% a.a."),
                     ("PIB Total", "PIB", "%"), ("Câmbio", "Dólar fim de ano", "R$")]


def focus() -> dict:
    ano = date.today().year
    linhas = []
    data_ref = None
    for nome, rotulo, unidade in FOCUS_INDICADORES:
        filtro = quote(f"Indicador eq '{nome}' and baseCalculo eq 0 and "
                       f"(DataReferencia eq '{ano}' or DataReferencia eq '{ano + 1}')")
        valores = _get(FOCUS.format(top=80, filtro=filtro))["value"]
        datas = sorted({v["Data"] for v in valores}, reverse=True)
        if not datas:
            continue
        ultima = datas[0]
        # comparação com ~4 semanas antes (a data publicada mais próxima de 28 dias atrás)
        alvo = (datetime.fromisoformat(ultima) - timedelta(days=28)).date().isoformat()
        antes = min(datas, key=lambda d: abs((datetime.fromisoformat(d) - datetime.fromisoformat(alvo)).days))
        def med(data, ref):
            return next((v["Mediana"] for v in valores if v["Data"] == data and v["DataReferencia"] == str(ref)), None)
        linhas.append({"rotulo": rotulo, "unidade": unidade,
                       "ano": med(ultima, ano), "ano_4sem": med(antes, ano),
                       "prox": med(ultima, ano + 1), "prox_4sem": med(antes, ano + 1)})
        data_ref = max(data_ref or ultima, ultima)
    return {"data": data_ref, "ano": ano, "linhas": linhas, "fonte": FONTE_FOCUS}


def main() -> None:
    caminho = RAIZ / "data" / "bcb.json"
    anterior = json.loads(caminho.read_text(encoding="utf-8")) if caminho.exists() else {}
    saida = {"atualizado_em": datetime.now().astimezone().isoformat()}
    for nome, func in (("selic", selic), ("ipca", ipca), ("dolar", dolar), ("focus", focus)):
        try:
            saida[nome] = func()
            print(f"{nome}: ok")
        except Exception as exc:  # noqa: BLE001
            print(f"{nome}: falhou ({exc}); mantendo valor anterior")
            if nome in anterior:
                saida[nome] = anterior[nome]
    caminho.write_text(json.dumps(saida, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
