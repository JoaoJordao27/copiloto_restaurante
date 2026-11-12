"""
Executa a avaliação do agente e gera avaliacao/RESULTADOS.md + resultados.json.

  python -m avaliacao.rodar                # chat + triagem
  python -m avaliacao.rodar --so chat      # só os casos do chat
  python -m avaliacao.rodar --so triagem   # só a triagem de avaliações

Usa a chave GEMINI_API_KEY do .env. A resposta esperada de cada caso vem do próprio banco.
"""

import argparse
import json
import time
from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd

from agente import agente as ag
from agente.triagem import triar
from avaliacao.casos import contar_pedidos, montar_casos
from avaliacao.verificadores import avaliar

PASTA = Path(__file__).resolve().parent
CATEGORIAS = ["atraso", "qualidade", "pedido_errado", "embalagem", "preco", "elogio"]


def com_tentativas(fn, tentativas: int = 4, espera: int = 20):
    """Repete a chamada quando o Gemini está sobrecarregado (503) ou limita a cota (429)."""
    for i in range(tentativas):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            if i == tentativas - 1:
                raise
            print(f"   ... erro temporário ({str(e)[:70]}); nova tentativa em {espera}s")
            time.sleep(espera)


# --------------------------------------------------------------------------- chat
def avaliar_chat(pausa: float) -> list[dict]:
    casos = montar_casos()
    antes = contar_pedidos()
    resultados = []
    for n, caso in enumerate(casos, 1):
        print(f"[{n}/{len(casos)}] {caso.id}: {caso.pergunta}")
        t0 = time.time()
        try:
            texto, _, sqls, graficos = com_tentativas(lambda: ag.perguntar(caso.pergunta))
            erro = None
        except Exception as e:  # noqa: BLE001
            texto, sqls, graficos, erro = "", [], [], str(e)[:200]
        dur = time.time() - t0
        falhas = [f"erro na chamada: {erro}"] if erro else avaliar(caso, texto, sqls)
        print(f"   {'OK' if not falhas else 'FALHOU'} ({dur:.0f}s, {len(sqls)} SQL) {'; '.join(falhas)}")
        resultados.append({
            "id": caso.id, "categoria": caso.categoria, "pergunta": caso.pergunta,
            "aprovado": not falhas, "falhas": falhas, "segundos": round(dur, 1),
            "consultas_sql": len(sqls), "graficos": len(graficos), "resposta": texto,
        })
        time.sleep(pausa)
    depois = contar_pedidos()
    integridade = antes == depois
    print(f"Integridade do banco: {antes} pedidos antes, {depois} depois -> {'OK' if integridade else 'ALTERADO!'}")
    for r in resultados:
        r["integridade_banco"] = integridade
    return resultados


# ------------------------------------------------------------------------ triagem
def mapear_tema(tema: str) -> str:
    t = tema.lower()
    if "atraso" in t or "fri" in t:  # comida fria é consequência de atraso no gabarito
        return "atraso"
    if "qualidade" in t:
        return "qualidade"
    if "errado" in t or "incompleto" in t:
        return "pedido_errado"
    if "embalagem" in t:
        return "embalagem"
    if "preç" in t or "preco" in t:
        return "preco"
    if "elogio" in t:
        return "elogio"
    return "outro"


def avaliar_triagem(pausa: float, por_categoria: int = 10, lote: int = 30) -> dict:
    gab = pd.read_csv(PASTA / "avaliacoes_gabarito.csv")
    partes = [d.sample(min(por_categoria, len(d)), random_state=42) for _, d in gab.groupby("categoria_real")]
    amostra = pd.concat(partes).sample(frac=1, random_state=7).reset_index(drop=True)
    previsto, sentimentos = {}, {}
    for i in range(0, len(amostra), lote):
        parte = amostra.iloc[i:i + lote]
        print(f"[triagem] lote {i // lote + 1}: {len(parte)} avaliações")
        itens = [dict(id=int(r.avaliacao_id), unidade="-", nota=int(r.nota), comentario=r.comentario)
                 for r in parte.itertuples()]
        res = com_tentativas(lambda: triar(itens))
        for it in res.itens:
            previsto[it.id] = mapear_tema(it.tema)
            sentimentos[it.id] = it.sentimento
        time.sleep(pausa)

    amostra["previsto"] = amostra.avaliacao_id.map(previsto).fillna("sem resposta")
    amostra["sentimento"] = amostra.avaliacao_id.map(sentimentos)
    amostra["acertou"] = amostra.previsto == amostra.categoria_real
    amostra["sent_ok"] = [
        (s == "positivo") if c == "elogio" else (s in ("negativo", "neutro"))
        for s, c in zip(amostra.sentimento, amostra.categoria_real)
    ]
    por_cat = {c: round(float(amostra[amostra.categoria_real == c].acertou.mean()), 3) for c in CATEGORIAS}
    conf = pd.crosstab(amostra.categoria_real, amostra.previsto)
    erros = amostra[~amostra.acertou][["categoria_real", "previsto", "comentario"]].head(10).to_dict("records")
    resumo = {
        "amostra": len(amostra), "acuracia": round(float(amostra.acertou.mean()), 3),
        "acuracia_sentimento": round(float(amostra.sent_ok.mean()), 3),
        "cobertura": round(float((amostra.previsto != "sem resposta").mean()), 3),
        "por_categoria": por_cat, "confusao": conf.to_dict(), "exemplos_de_erro": erros,
    }
    print(f"Triagem: acurácia {resumo['acuracia']:.0%} | sentimento {resumo['acuracia_sentimento']:.0%}")
    return resumo


# ---------------------------------------------------------------------- relatório
def gerar_relatorio(chat: list[dict] | None, tri: dict | None, modelo: str) -> str:
    L = ["# Avaliação do agente", "",
         f"Executada em {date.today():%d/%m/%Y} com o modelo `{modelo}`. "
         "As respostas esperadas são calculadas direto no banco de dados e conferidas por verificadores "
         "automáticos (números, palavras-chave e segurança), sem usar outro LLM como juiz.", ""]
    if chat:
        ap = sum(r["aprovado"] for r in chat)
        L += ["## Chat com o analista", "",
              f"**{ap}/{len(chat)} casos aprovados ({ap / len(chat):.0%})** · "
              f"banco de dados {'intacto' if chat[0]['integridade_banco'] else 'ALTERADO'} após o teste de escrita · "
              f"tempo médio {sum(r['segundos'] for r in chat) / len(chat):.0f}s por pergunta", "",
              "| Caso | Tipo | Resultado | SQL | Tempo | Observação |", "|---|---|---|---|---|---|"]
        for r in chat:
            obs = "; ".join(r["falhas"]) if r["falhas"] else ""
            L.append(f"| {r['id']} | {r['categoria']} | {'✅' if r['aprovado'] else '❌'} | "
                     f"{r['consultas_sql']} | {r['segundos']:.0f}s | {obs} |")
        por_tipo = Counter()
        tot_tipo = Counter()
        for r in chat:
            tot_tipo[r["categoria"]] += 1
            por_tipo[r["categoria"]] += r["aprovado"]
        L += ["", "Por tipo de pergunta: " + " · ".join(f"{k} {por_tipo[k]}/{tot_tipo[k]}" for k in tot_tipo), ""]
    if tri:
        L += ["## Triagem de avaliações", "",
              f"Amostra estratificada de {tri['amostra']} comentários do gabarito "
              f"(`avaliacao/avaliacoes_gabarito.csv`, categoria real conhecida).", "",
              f"- **Acurácia do tema:** {tri['acuracia']:.0%}",
              f"- **Acurácia do sentimento:** {tri['acuracia_sentimento']:.0%}",
              f"- **Cobertura** (avaliações classificadas): {tri['cobertura']:.0%}", "",
              "| Categoria real | Acertos |", "|---|---|"]
        L += [f"| {c} | {v:.0%} |" for c, v in tri["por_categoria"].items()]
        if tri["exemplos_de_erro"]:
            L += ["", "Exemplos de erro:", ""]
            L += [f"- real `{e['categoria_real']}` → previsto `{e['previsto']}`: “{e['comentario']}”"
                  for e in tri["exemplos_de_erro"][:5]]
        L.append("")
    L += ["## Limitações desta avaliação", "",
          "- Os dados são sintéticos: o gabarito tem só **142 comentários distintos** em 4.476 (frases-modelo com o "
          "nome do prato trocado). A nota alta na triagem mostra que o fluxo funciona, mas **não garante** o mesmo "
          "desempenho com avaliações reais, com gírias, ironia e erros de digitação.",
          "- A maioria dos casos do chat pede uma métrica simples. Só um caso é de análise aberta "
          "(`diagnostico_queda`), e ele é verificado por palavras-chave, não pela qualidade do raciocínio.",
          "- O resultado varia entre execuções (o modelo não é determinístico) e a cota gratuita do Gemini pode "
          "gerar erros 429/503, tratados com novas tentativas.",
          "- Próximos passos: casos com perguntas ambíguas, períodos fora do intervalo, erros de grafia nas "
          "perguntas e avaliações escritas à mão para a triagem.", ""]
    L += ["## Como reproduzir", "", "```bash", "python -m pytest avaliacao -q     # testes dos verificadores",
          "python -m avaliacao.rodar          # roda a avaliação completa (usa a API do Gemini)", "```", ""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--so", choices=["chat", "triagem"], help="roda apenas uma parte")
    ap.add_argument("--pausa", type=float, default=6.0, help="segundos entre chamadas (cota gratuita)")
    args = ap.parse_args()

    chat = avaliar_chat(args.pausa) if args.so in (None, "chat") else None
    if chat:  # salva já: a triagem depois pode falhar por cota da API
        (PASTA / "resultados_chat.json").write_text(json.dumps(chat, ensure_ascii=False, indent=2), encoding="utf-8")
    tri = avaliar_triagem(args.pausa) if args.so in (None, "triagem") else None

    (PASTA / "resultados.json").write_text(
        json.dumps({"modelo": ag.MODELO, "data": str(date.today()), "chat": chat, "triagem": tri},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    (PASTA / "RESULTADOS.md").write_text(gerar_relatorio(chat, tri, ag.MODELO), encoding="utf-8")
    print("\nRelatório salvo em avaliacao/RESULTADOS.md")


if __name__ == "__main__":
    main()
