"""Agrupa a mesma notícia vinda de fontes diferentes e gera título/resumo em PT-BR.

Lê data/noticias.json, acrescenta "grupos" a cada aba e grava de volta.
Se o Gemini falhar ou não houver chave, a aba continua com a lista simples (sem grupos).
Cache: se os ids de entrada de uma aba não mudaram, reaproveita os grupos anteriores.
"""
import hashlib
import json
import time
from pathlib import Path

import yaml

from src.ia import gemini

RAIZ = Path(__file__).resolve().parent.parent.parent
MAX_ITENS = 40
LIMITE_S = 480  # orçamento total de tempo para a IA nesta execução

PROMPT = """Você é editor de um portal de notícias pessoal em português do Brasil.
Abaixo há uma lista de manchetes (id, fonte, título, resumo) de veículos diferentes.

Tarefa:
1. Agrupe as manchetes que tratam do MESMO fato/assunto. Manchete sem par forma um grupo sozinha.
2. Para cada grupo escreva "titulo" (neutro, em PT-BR, traduza se estiver em outro idioma).
   Só para grupos com 2 ou mais manchetes escreva "resumo" (1 a 2 frases, só com o que consta nas
   manchetes e resumos; não invente nada). Para manchete sozinha, "resumo" é string vazia.
3. {instrucao_enquadramento}
4. Use cada id exatamente uma vez. Ordene os grupos do mais ao menos relevante.

Responda SOMENTE JSON neste formato:
{{"grupos":[{{"titulo":"...","resumo":"...","itens":[{{"id":"...","enquadramento":"..."}}]}}]}}

Manchetes:
{lista}
"""
ENQ_SIM = ('Em "enquadramento", escreva por veículo, em até 15 palavras, como a manchete enquadra o fato '
           "(ênfase, termos escolhidos, quem aparece como protagonista ou culpado). Descreva sem opinar.")
ENQ_NAO = 'Deixe "enquadramento" como string vazia.'


def _validar(resp: dict, itens: dict[str, dict]) -> list[dict]:
    grupos, usados = [], set()
    for g in resp.get("grupos", []):
        ids = [i for i in g.get("itens", []) if isinstance(i, dict) and i.get("id") in itens and i["id"] not in usados]
        if not ids:
            continue
        usados.update(i["id"] for i in ids)
        grupos.append({"titulo": str(g.get("titulo", "")).strip(), "resumo": str(g.get("resumo", "")).strip(),
                       "itens": [{"id": i["id"], "enquadramento": str(i.get("enquadramento", "")).strip()} for i in ids]})
    for id_, it in itens.items():  # o que o modelo esqueceu vira grupo solitário
        if id_ not in usados:
            grupos.append({"titulo": it["titulo"], "resumo": it["resumo"], "itens": [{"id": id_, "enquadramento": ""}]})
    return grupos


def _montar(grupos: list[dict], itens: dict[str, dict]) -> list[dict]:
    saida = []
    for g in grupos:
        membros = [{**itens[i["id"]], "enquadramento": i["enquadramento"]} for i in g["itens"]]
        resumo = g["resumo"] or (membros[0]["resumo"] if len(membros) == 1 else "")
        saida.append({"titulo": g["titulo"] or membros[0]["titulo"], "resumo": resumo,
                      "data": max(m["data"] for m in membros), "itens": membros})
    return saida  # mantém a ordem de relevância escolhida pelo modelo


def agrupar_aba(aba: dict, comparar: bool, cache: dict) -> dict | None:
    candidatos = aba["itens"][:MAX_ITENS]
    if not candidatos:
        return None
    itens = {i["id"]: i for i in candidatos}
    chave = hashlib.sha1(("|".join(sorted(itens)) + str(comparar)).encode()).hexdigest()
    if cache.get("chave") == chave:
        return cache
    lista = "\n".join(f'- id={i["id"]} | {i["fonte"]} | {i["titulo"]} | {i["resumo"][:200]}' for i in candidatos)
    prompt = PROMPT.format(instrucao_enquadramento=ENQ_SIM if comparar else ENQ_NAO, lista=lista)
    grupos = _validar(gemini.gerar_json(prompt), itens)
    return {"chave": chave, "grupos": grupos}


def main() -> None:
    cfg = yaml.safe_load((RAIZ / "config" / "feeds.yml").read_text(encoding="utf-8"))
    caminho = RAIZ / "data" / "noticias.json"
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    cache_p = RAIZ / "data" / "cache_ia.json"
    cache = json.loads(cache_p.read_text(encoding="utf-8")) if cache_p.exists() else {}
    if not gemini.disponivel():
        print("GEMINI_API_KEY ausente: pulando IA")
        return
    inicio = time.monotonic()
    for chave, aba in dados["abas"].items():
        if time.monotonic() - inicio > LIMITE_S:
            print(f"{chave}: sem tempo para IA nesta rodada; mantendo lista simples")
            continue
        try:
            res = agrupar_aba(aba, bool(cfg["abas"][chave].get("comparar")), cache.get(chave, {}))
        except Exception as exc:  # noqa: BLE001 — IA nunca derruba o portal
            print(f"{chave}: IA falhou ({exc}); mantendo lista simples", flush=True)
            continue
        if res:
            cache[chave] = res
            itens = {i["id"]: i for i in aba["itens"]}
            aba["grupos"] = _montar(res["grupos"], itens)
            print(f"{chave}: {len(aba['grupos'])} grupos", flush=True)
        # grava a cada aba: se o passo for interrompido, o que já foi feito fica
        caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
        cache_p.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
