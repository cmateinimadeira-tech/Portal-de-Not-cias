"""Agrupa a mesma notícia vinda de fontes diferentes, ordena por relevância e resume.

Fluxo por aba:
1. Gemini agrupa as manchetes que tratam do mesmo fato e dá um título em PT-BR.
2. Relevância = quantos veículos diferentes cobriram o fato (portais grandes pesam mais).
3. Para os destaques (fato coberto por 2+ veículos), extrai o texto público das matérias
   e pede ao Gemini um resumo mais completo, com pontos-chave e, na política, o
   enquadramento de cada veículo. O texto extraído não é gravado; só o resumo.

Cache:
- agrupamento: se as manchetes da aba não mudaram, não chama o Gemini;
- resumo de destaque: guardado pelo conjunto de matérias do grupo, então um fato já
  resumido só é refeito quando entra uma matéria nova nele.
Se o Gemini falhar, a aba continua com a lista simples.
"""
import hashlib
import json
import time
from pathlib import Path

import yaml

from src.coletores.texto import extrair_varios
from src.ia import gemini

RAIZ = Path(__file__).resolve().parent.parent.parent
MAX_ITENS = 110         # manchetes mais recentes enviadas para agrupamento
MAX_DESTAQUES = 12      # fatos com resumo completo por aba
MAX_TEXTOS_GRUPO = 4    # matérias lidas por fato
LIMITE_S = 600          # orçamento total de tempo para a IA nesta execução
PESO_GRANDE = 0.5       # bônus por portal grande no ranking

PROMPT_GRUPOS = """Você é editor de um portal de notícias em português do Brasil.
Abaixo há manchetes (id | veículo | título | resumo) de veículos diferentes.

Agrupe as manchetes que tratam do MESMO FATO ESPECÍFICO (mesmo acontecimento, decisão,
anúncio ou declaração). Tema parecido não basta: "duas notícias sobre IA" NÃO são o mesmo fato.
Manchete sem par forma um grupo sozinha. Use cada id exatamente uma vez.

Para cada grupo dê um "titulo" curto, neutro e informativo em PT-BR, com ortografia correta
(traduza se a manchete estiver em outro idioma). Não invente informação.

Responda SOMENTE JSON: {{"grupos":[{{"titulo":"...","ids":["..."]}}]}}

Manchetes:
{lista}
"""

PROMPT_RESUMOS = """Você é editor de um portal de notícias em português do Brasil.
Para cada fato abaixo há o texto (às vezes parcial) de matérias de veículos diferentes.

Para cada fato escreva:
- "resumo": 3 a 5 frases em PT-BR com o essencial (o quê, quem, quando, por quê, o que muda),
  usando só o que está nos textos. Se os veículos divergirem em algum dado, diga.
- "pontos": 2 a 4 pontos-chave curtos.
{instrucao_enquadramento}
Não invente nada além dos textos. Ortografia correta.

Responda SOMENTE JSON:
{{"fatos":[{{"fato":"F1","resumo":"...","pontos":["..."],"enquadramentos":{{"<id>":"..."}}}}]}}

{blocos}
"""
ENQ_SIM = ('- "enquadramentos": para cada id, em até 20 palavras, como aquele veículo enquadra o fato '
           "(ênfase, termos escolhidos, quem aparece como protagonista ou responsável, o que omite em "
           "relação aos outros). Descreva sem opinar.")
ENQ_NAO = '- "enquadramentos": objeto vazio {{}}.'


def _hash(*partes: str) -> str:
    return hashlib.sha1("|".join(partes).encode()).hexdigest()[:16]


# ---------- 1. agrupamento ----------

def _agrupar(candidatos: list[dict]) -> list[dict]:
    itens = {i["id"]: i for i in candidatos}
    lista = "\n".join(f'- {i["id"]} | {i["fonte"]} | {i["titulo"]} | {i["resumo"][:160]}' for i in candidatos)
    resp = gemini.gerar_json(PROMPT_GRUPOS.format(lista=lista))
    grupos, usados = [], set()
    for g in resp.get("grupos", []):
        ids = [i for i in g.get("ids", []) if isinstance(i, str) and i in itens and i not in usados]
        if ids:
            usados.update(ids)
            grupos.append({"titulo": str(g.get("titulo", "")).strip(), "ids": ids})
    for id_ in itens:  # o que o modelo esqueceu vira grupo solitário
        if id_ not in usados:
            grupos.append({"titulo": itens[id_]["titulo"], "ids": [id_]})
    return grupos


# ---------- 2. relevância ----------

def _pontuar(grupo: dict, itens: dict, grandes: set[str]) -> float:
    fontes = {itens[i]["fonte"] for i in grupo["ids"]}
    return len(fontes) + PESO_GRANDE * len(fontes & grandes)


# ---------- 3. resumos dos destaques ----------

def _escolher_materias(ids: list[str], itens: dict) -> list[str]:
    """Uma matéria por veículo, priorizando as que permitem extração."""
    por_fonte: dict[str, str] = {}
    for i in ids:
        f = itens[i]["fonte"]
        if f not in por_fonte or "news.google.com" in itens[por_fonte[f]]["link"]:
            por_fonte[f] = i
    return list(por_fonte.values())


def _resumir(destaques: list[dict], itens: dict, comparar: bool, cache: dict) -> None:
    pendentes = [g for g in destaques if g["chave_resumo"] not in cache]
    if pendentes:
        escolhidos = {g["chave_resumo"]: _escolher_materias(g["ids"], itens)
                      for g in pendentes}
        urls = [itens[i]["link"] for ids in escolhidos.values() for i in ids[:MAX_TEXTOS_GRUPO]]
        textos = extrair_varios(urls)
        blocos = []
        for n, g in enumerate(pendentes, 1):
            g["_fato"] = f"F{n}"
            partes = [f"### F{n}: {g['titulo']}"]
            for i in escolhidos[g["chave_resumo"]]:
                it = itens[i]
                corpo = textos.get(it["link"]) or it["resumo"] or "(sem texto disponível; use só o título)"
                partes.append(f"[id={i} | {it['fonte']}] {it['titulo']}\n{corpo}")
            blocos.append("\n\n".join(partes))
        prompt = PROMPT_RESUMOS.format(instrucao_enquadramento=ENQ_SIM if comparar else ENQ_NAO,
                                       blocos="\n\n".join(blocos))
        resp = gemini.gerar_json(prompt)
        por_fato = {f.get("fato"): f for f in resp.get("fatos", []) if isinstance(f, dict)}
        for g in pendentes:
            f = por_fato.get(g["_fato"])
            if f and f.get("resumo"):
                enq = f.get("enquadramentos") if isinstance(f.get("enquadramentos"), dict) else {}
                cache[g["chave_resumo"]] = {
                    "resumo": str(f["resumo"]).strip(),
                    "pontos": [str(p).strip() for p in f.get("pontos", []) if str(p).strip()][:4],
                    "enquadramentos": {k: str(v).strip() for k, v in enq.items() if k in g["ids"]},
                    "usado_em": time.time(),
                }
    for g in destaques:
        r = cache.get(g["chave_resumo"])
        if r:
            r["usado_em"] = time.time()
            g.update(resumo=r["resumo"], pontos=r["pontos"], enquadramentos=r["enquadramentos"])


# ---------- montagem ----------

def _montar(grupos: list[dict], itens: dict) -> list[dict]:
    saida = []
    for g in grupos:
        membros = sorted((itens[i] for i in g["ids"]), key=lambda m: m["data"], reverse=True)
        enq = g.get("enquadramentos", {})
        saida.append({
            "titulo": g["titulo"] or membros[0]["titulo"],
            "resumo": g.get("resumo") or (membros[0]["resumo"] if len(membros) == 1 else ""),
            "pontos": g.get("pontos", []),
            "destaque": g.get("destaque", False),
            "n_fontes": len({m["fonte"] for m in membros}),
            "data": membros[0]["data"],
            "itens": [{**m, "enquadramento": enq.get(m["id"], "")} for m in membros],
        })
    return saida


def processar_aba(aba: dict, cfg_aba: dict, grandes: set[str], cache: dict) -> list[dict] | None:
    candidatos = aba["itens"][:MAX_ITENS]
    if not candidatos:
        return None
    itens = {i["id"]: i for i in aba["itens"]}
    chave = _hash(*sorted(i["id"] for i in candidatos))
    if cache.get("chave") == chave:
        grupos = cache["grupos"]
    else:
        grupos = _agrupar(candidatos)
        cache.update(chave=chave, grupos=grupos)
    grupos = [dict(g) for g in grupos]
    for g in grupos:
        g["score"] = _pontuar(g, itens, grandes)
        g["chave_resumo"] = _hash(*sorted(g["ids"]), str(bool(cfg_aba.get("comparar"))))
    # mais veículos primeiro; empate decide pela matéria mais recente (datas ISO em UTC)
    grupos.sort(key=lambda g: max(itens[i]["data"] for i in g["ids"]), reverse=True)
    grupos.sort(key=lambda g: g["score"], reverse=True)
    destaques = [g for g in grupos if len({itens[i]["fonte"] for i in g["ids"]}) >= 2][:MAX_DESTAQUES]
    for g in destaques:
        g["destaque"] = True
    try:
        _resumir(destaques, itens, bool(cfg_aba.get("comparar")), cache.setdefault("resumos", {}))
    except Exception as exc:  # noqa: BLE001 — sem resumo completo, segue com os grupos
        print(f"  resumos falharam ({exc}); destaques ficam só com título", flush=True)
    # descarta resumos que não aparecem há mais de 3 dias
    limite = time.time() - 3 * 86400
    cache["resumos"] = {k: v for k, v in cache["resumos"].items() if v.get("usado_em", 0) > limite}
    return _montar(grupos, itens)


def main() -> None:
    cfg = yaml.safe_load((RAIZ / "config" / "feeds.yml").read_text(encoding="utf-8"))
    grandes = set(cfg.get("grandes", []))
    caminho = RAIZ / "data" / "noticias.json"
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    cache_p = RAIZ / "data" / "cache_ia.json"
    cache = json.loads(cache_p.read_text(encoding="utf-8")) if cache_p.exists() else {}
    if not gemini.disponivel():
        print("GEMINI_API_KEY ausente: pulando IA")
        return
    if not gemini.testar():
        print("Gemini não respondeu ao teste: pulando IA nesta rodada")
        return
    inicio = time.monotonic()
    for chave, aba in dados["abas"].items():
        if time.monotonic() - inicio > LIMITE_S:
            print(f"{chave}: sem tempo para IA nesta rodada; mantendo lista simples")
            continue
        c = cache.get(chave, {})
        if "resumos" not in c:  # formato antigo do cache
            c = {}
        try:
            grupos = processar_aba(aba, cfg["abas"][chave], grandes, c)
        except Exception as exc:  # noqa: BLE001 — IA nunca derruba o portal
            print(f"{chave}: IA falhou ({exc}); mantendo lista simples", flush=True)
            continue
        if grupos:
            cache[chave] = c
            aba["grupos"] = grupos
            n = sum(1 for g in grupos if g["destaque"])
            print(f"{chave}: {len(grupos)} grupos, {n} destaques", flush=True)
        # grava a cada aba: se o passo for interrompido, o que já foi feito fica
        caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
        cache_p.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
