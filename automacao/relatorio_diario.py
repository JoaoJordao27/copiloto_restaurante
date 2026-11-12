"""
Relatório diário do restaurante: indicadores do dia, comparação com a média dos mesmos dias da semana
nas 4 semanas anteriores, alertas por unidade e reclamações do dia. Só precisa de pandas (a IA é opcional).

  python automacao/relatorio_diario.py                     # último dia com dados, em texto
  python automacao/relatorio_diario.py --data 2026-10-31   # um dia específico
  python automacao/relatorio_diario.py --formato html      # versão para e-mail
  python automacao/relatorio_diario.py --formato json      # usado pelo n8n
  python automacao/relatorio_diario.py --ia                # inclui resumo escrito pelo Gemini
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import date, timedelta
from html import escape
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
BANCO = RAIZ / "dados" / "restaurante.db"
SEMANA = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]

# Limites que disparam alerta (ajuste ao seu negócio)
LIMITES = {"tempo_max_min": 45, "cancel_max_pct": 6.0, "queda_fat_pct": 20.0, "nota_min": 3.5, "min_avaliacoes": 5}


# ------------------------------------------------------------------ formatação
def brl(v: float) -> str:
    return "R$ " + f"{v:,.0f}".replace(",", ".")


def num(v: float, casas: int = 1) -> str:
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def pct(v: float) -> str:
    return f"{v:+.1f}%".replace(".", ",")


def ultimos_4(dia_semana: str) -> str:
    """'4 terças anteriores' (evita erro de concordância de gênero)."""
    plural = dia_semana + ("s" if dia_semana.endswith(("o", "a")) else "")
    return f"4 {plural} anteriores"


# ----------------------------------------------------------------------- dados
def carregar(banco: Path = BANCO) -> tuple[pd.DataFrame, pd.DataFrame]:
    con = sqlite3.connect(f"file:{banco}?mode=ro", uri=True)
    try:
        ped = pd.read_sql_query(
            "SELECT data, unidade, status, valor_total, tempo_entrega_min FROM pedidos", con)
        aval = pd.read_sql_query("SELECT data, unidade, nota, comentario FROM avaliacoes", con)
    finally:
        con.close()
    return ped, aval


def indicadores(ped: pd.DataFrame, aval: pd.DataFrame) -> dict:
    ent = ped[ped.status != "cancelado"]
    return {
        "faturamento": float(ent.valor_total.sum()),
        "pedidos": int(len(ent)),
        "ticket_medio": float(ent.valor_total.mean()) if len(ent) else 0.0,
        "cancelamento_pct": float((ped.status == "cancelado").mean() * 100) if len(ped) else 0.0,
        "tempo_medio_min": float(ent.tempo_entrega_min.mean()) if len(ent) else 0.0,
        "nota_media": float(aval.nota.mean()) if len(aval) else None,
        "avaliacoes": int(len(aval)),
    }


def media_mesmo_dia_semana(ped: pd.DataFrame, dia: date, semanas: int = 4) -> float | None:
    """Faturamento médio nos mesmos dias da semana das `semanas` semanas anteriores."""
    datas = [(dia - timedelta(days=7 * k)).isoformat() for k in range(1, semanas + 1)]
    base = ped[ped.data.isin(datas) & (ped.status != "cancelado")]
    dias_com_dados = base.data.nunique()
    return float(base.valor_total.sum() / dias_com_dados) if dias_com_dados else None


def alertas_da_unidade(nome: str, ind: dict, fat_base: float | None, lim: dict = LIMITES) -> list[str]:
    """Regras simples e explícitas: cada alerta diz o que passou do limite."""
    out = []
    if ind["pedidos"] and ind["tempo_medio_min"] > lim["tempo_max_min"]:
        out.append(f"{nome}: tempo médio de entrega de {num(ind['tempo_medio_min'])} min "
                   f"(limite {lim['tempo_max_min']} min)")
    if ind["cancelamento_pct"] > lim["cancel_max_pct"]:
        out.append(f"{nome}: {num(ind['cancelamento_pct'])}% de cancelamentos (limite {num(lim['cancel_max_pct'])}%)")
    if fat_base:
        variacao = (ind["faturamento"] / fat_base - 1) * 100
        if variacao < -lim["queda_fat_pct"]:
            out.append(f"{nome}: faturamento {pct(variacao)} frente ao habitual para o dia da semana "
                       f"({brl(ind['faturamento'])} contra {brl(fat_base)})")
    if ind["nota_media"] is not None and ind["avaliacoes"] >= lim["min_avaliacoes"] and ind["nota_media"] < lim["nota_min"]:
        out.append(f"{nome}: nota média de {num(ind['nota_media'], 2)} em {ind['avaliacoes']} avaliações "
                   f"(mínimo {num(lim['nota_min'])})")
    return out


# --------------------------------------------------------------------- relatório
def ultima_data(ped: pd.DataFrame) -> date:
    return date.fromisoformat(ped.data.max())


def gerar(data: str | None = None, ia: bool = False, banco: Path = BANCO) -> dict:
    """Monta o relatório do dia. `data` = 'AAAA-MM-DD', 'ontem' ou None (último dia com dados)."""
    ped, aval = carregar(banco)
    if data == "ontem":
        dia = date.today() - timedelta(days=1)
    else:
        dia = date.fromisoformat(data) if data and data != "ultima" else ultima_data(ped)
    iso = dia.isoformat()
    p_dia, a_dia = ped[ped.data == iso], aval[aval.data == iso]
    if p_dia.empty:
        raise ValueError(f"Sem pedidos em {iso}. Dados disponíveis até {ped.data.max()}.")

    geral = indicadores(p_dia, a_dia)
    base_geral = media_mesmo_dia_semana(ped, dia)
    geral["faturamento_habitual"] = base_geral
    geral["variacao_faturamento_pct"] = (geral["faturamento"] / base_geral - 1) * 100 if base_geral else None

    unidades, alertas = [], []
    for un in sorted(p_dia.unidade.unique()):
        ind = indicadores(p_dia[p_dia.unidade == un], a_dia[a_dia.unidade == un])
        base = media_mesmo_dia_semana(ped[ped.unidade == un], dia)
        ind["unidade"] = un
        ind["faturamento_habitual"] = base
        ind["variacao_faturamento_pct"] = (ind["faturamento"] / base - 1) * 100 if base else None
        unidades.append(ind)
        alertas += alertas_da_unidade(un, ind, base)

    ruins = a_dia[a_dia.nota <= 2].sort_values("nota")
    reclamacoes = [{"unidade": r.unidade, "nota": int(r.nota), "comentario": r.comentario}
                   for r in ruins.head(5).itertuples()]

    dados = {
        "data": iso, "dia_semana": SEMANA[dia.weekday()], "geral": geral, "unidades": unidades,
        "alertas": alertas, "reclamacoes": reclamacoes, "total_reclamacoes": int(len(ruins)),
        "limites": LIMITES, "resumo_ia": None,
    }
    if ia:
        dados["resumo_ia"] = resumo_ia(dados)
    dados["assunto"] = assunto(dados)
    dados["texto"] = para_texto(dados)
    dados["html"] = para_html(dados)
    return dados


def assunto(d: dict) -> str:
    dia = date.fromisoformat(d["data"]).strftime("%d/%m")
    n = len(d["alertas"])
    estado = f"{n} alerta{'s' if n != 1 else ''}" if n else "sem alertas"
    return f"Sabor da Casa · {dia} ({d['dia_semana']}) · {brl(d['geral']['faturamento'])} · {estado}"


def resumo_ia(d: dict) -> str | None:
    """Parágrafo executivo escrito pelo Gemini a partir dos números (opcional; falha sem derrubar o relatório)."""
    try:
        sys.path.insert(0, str(RAIZ))
        from dotenv import load_dotenv
        from google import genai

        load_dotenv(RAIZ / ".env")
        enxuto = {k: d[k] for k in ("data", "dia_semana", "geral", "unidades", "alertas", "reclamacoes")}
        prompt = (
            "Você escreve o resumo executivo diário para o dono de um restaurante delivery. Com base APENAS "
            "nestes números, escreva 3 a 4 frases em português do Brasil: como foi o dia, o que mais chama "
            "atenção e uma ação prática. Não invente valores.\n\n" + json.dumps(enxuto, ensure_ascii=False, default=str)
        )
        cliente = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        modelo = os.getenv("MODELO_GEMINI", "gemini-3.5-flash-lite")
        return (cliente.models.generate_content(model=modelo, contents=prompt).text or "").strip() or None
    except Exception as e:  # noqa: BLE001
        print(f"[aviso] resumo por IA indisponível: {str(e)[:120]}", file=sys.stderr)
        return None


# ----------------------------------------------------------------------- saídas
def _linha_ind(i: dict) -> str:
    nota = num(i["nota_media"], 2) if i["nota_media"] is not None else "–"
    return (f"{brl(i['faturamento'])} · {i['pedidos']} pedidos · ticket R$ {num(i['ticket_medio'], 2)} · "
            f"{num(i['cancelamento_pct'])}% cancel. · {num(i['tempo_medio_min'])} min · nota {nota}")


def para_texto(d: dict) -> str:
    g = d["geral"]
    dia = date.fromisoformat(d["data"]).strftime("%d/%m/%Y")
    L = [f"RELATÓRIO DIÁRIO · Sabor da Casa · {dia} ({d['dia_semana']})", ""]
    if g["variacao_faturamento_pct"] is not None:
        L.append(f"Faturamento {brl(g['faturamento'])} ({pct(g['variacao_faturamento_pct'])} frente à média de "
                 f"{ultimos_4(d['dia_semana'])}: {brl(g['faturamento_habitual'])})")
    else:
        L.append(f"Faturamento {brl(g['faturamento'])}")
    L += ["Geral: " + _linha_ind(g), "", "Por unidade:"]
    L += [f"- {u['unidade']}: " + _linha_ind(u) for u in d["unidades"]]
    L += ["", "ALERTAS" if d["alertas"] else "Sem alertas hoje."]
    L += [f"! {a}" for a in d["alertas"]]
    if d["reclamacoes"]:
        L += ["", f"Reclamações do dia ({d['total_reclamacoes']} avaliações com nota 1 ou 2):"]
        L += [f"- {r['unidade']} ({r['nota']}★): {r['comentario']}" for r in d["reclamacoes"]]
    if d["resumo_ia"]:
        L += ["", "Resumo: " + d["resumo_ia"]]
    return "\n".join(L)


def para_html(d: dict) -> str:
    """HTML com estilos inline (compatível com clientes de e-mail), nas cores da marca."""
    g = d["geral"]
    dia = date.fromisoformat(d["data"]).strftime("%d/%m/%Y")
    var = (f'<span style="color:{"#1F8A4C" if g["variacao_faturamento_pct"] >= 0 else "#D93F77"}">'
           f'{pct(g["variacao_faturamento_pct"])}</span> frente à média de {ultimos_4(d["dia_semana"])}'
           if g["variacao_faturamento_pct"] is not None else "")

    def linha(u):
        v = u["variacao_faturamento_pct"]
        nota = num(u["nota_media"], 2) if u["nota_media"] is not None else "–"
        return (f'<tr><td style="padding:8px 10px;font-weight:600">{escape(u["unidade"])}</td>'
                f'<td style="padding:8px 10px;text-align:right">{brl(u["faturamento"])}'
                f'{" (" + pct(v) + ")" if v is not None else ""}</td>'
                f'<td style="padding:8px 10px;text-align:right">{u["pedidos"]}</td>'
                f'<td style="padding:8px 10px;text-align:right">{num(u["cancelamento_pct"])}%</td>'
                f'<td style="padding:8px 10px;text-align:right">{num(u["tempo_medio_min"])} min</td>'
                f'<td style="padding:8px 10px;text-align:right">{nota}</td></tr>')

    alertas = "".join(f'<li style="margin:4px 0">{escape(a)}</li>' for a in d["alertas"])
    bloco_alertas = (
        f'<div style="background:#FBEBC1;border-left:5px solid #D93F77;border-radius:10px;padding:12px 16px;margin:18px 0">'
        f'<b>Alertas</b><ul style="margin:8px 0 0;padding-left:18px">{alertas}</ul></div>'
        if d["alertas"] else
        '<div style="background:#E4F2E9;border-radius:10px;padding:12px 16px;margin:18px 0">Sem alertas hoje. ✅</div>')
    recl = "".join(f'<li style="margin:4px 0"><b>{escape(r["unidade"])}</b> ({r["nota"]}★): {escape(r["comentario"])}</li>'
                   for r in d["reclamacoes"])
    bloco_recl = (f'<h3 style="font-family:Georgia,serif;margin:22px 0 6px">Reclamações do dia ({d["total_reclamacoes"]})</h3>'
                  f'<ul style="margin:0;padding-left:18px">{recl}</ul>') if recl else ""
    bloco_ia = (f'<p style="background:#FFFAF0;border:1px solid #DCCBA6;border-radius:10px;padding:12px 16px">'
                f'{escape(d["resumo_ia"])}</p>') if d["resumo_ia"] else ""
    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;max-width:680px;margin:auto;color:#17332E">'
        '<div style="background:#1B4F47;color:#F8F0DC;padding:18px 24px;border-radius:14px 14px 0 0">'
        f'<div style="font-family:Georgia,serif;font-size:24px">Sabor da Casa</div>'
        f'<div style="opacity:.8">Relatório diário · {dia} ({d["dia_semana"]})</div></div>'
        '<div style="background:#F4EBD8;padding:22px 24px;border-radius:0 0 14px 14px">'
        '<div style="background:#F0B323;border-radius:14px;padding:16px 20px">'
        '<div style="font-size:13px">Faturamento do dia</div>'
        f'<div style="font-family:Georgia,serif;font-size:36px;font-weight:bold">{brl(g["faturamento"])}</div></div>'
        f'<p style="margin:10px 0 0">{var}</p>'
        f'<p style="margin:6px 0 0;font-size:14px">{g["pedidos"]} pedidos · ticket médio R$ {num(g["ticket_medio"], 2)} · '
        f'{num(g["cancelamento_pct"])}% de cancelamentos · {num(g["tempo_medio_min"])} min de entrega</p>'
        f'{bloco_alertas}{bloco_ia}'
        '<table style="width:100%;border-collapse:collapse;background:#FFFAF0;border-radius:10px;font-size:14px">'
        '<tr style="background:#FBEBC1"><th style="padding:8px 10px;text-align:left">Unidade</th>'
        '<th style="padding:8px 10px;text-align:right">Faturamento</th><th style="padding:8px 10px;text-align:right">Pedidos</th>'
        '<th style="padding:8px 10px;text-align:right">Cancel.</th><th style="padding:8px 10px;text-align:right">Entrega</th>'
        '<th style="padding:8px 10px;text-align:right">Nota</th></tr>'
        + "".join(linha(u) for u in d["unidades"]) +
        f'</table>{bloco_recl}</div></div>')


def main():
    ap = argparse.ArgumentParser(description="Gera o relatório diário do restaurante.")
    ap.add_argument("--data", help="AAAA-MM-DD, 'ontem' ou omitido (= último dia com dados)")
    ap.add_argument("--formato", choices=["texto", "html", "json"], default="texto")
    ap.add_argument("--ia", action="store_true", help="inclui resumo escrito pelo Gemini")
    ap.add_argument("--saida", help="grava em arquivo em vez de imprimir")
    a = ap.parse_args()
    try:
        d = gerar(a.data, ia=a.ia)
    except ValueError as e:
        sys.exit(str(e))
    saida = {"texto": d["texto"], "html": d["html"], "json": json.dumps(d, ensure_ascii=False, indent=2)}[a.formato]
    if a.saida:
        Path(a.saida).write_text(saida, encoding="utf-8")
        print(f"Relatório salvo em {a.saida}")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(saida)


if __name__ == "__main__":
    main()
