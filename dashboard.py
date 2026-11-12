"""Painel de indicadores do restaurante. Só consulta o banco (não usa IA, não gasta cota)."""

import sqlite3

import pandas as pd
import plotly.express as px
import streamlit as st

from agente.agente import BANCO
from visual import COR_UNIDADE, PALETA, brl, estilizar, num

MESES = ["2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
NOME_MES = {"2026-06": "jun/26", "2026-07": "jul/26", "2026-08": "ago/26", "2026-09": "set/26", "2026-10": "out/26"}
DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
CONFIG = {"displayModeBar": False}


@st.cache_data(ttl=600)
def carregar():
    con = sqlite3.connect(f"file:{BANCO}?mode=ro", uri=True)
    try:
        ped = pd.read_sql_query(
            "SELECT id, data, hora, dia_semana, unidade, canal, status, valor_total, tempo_entrega_min "
            "FROM pedidos", con)
        itens = pd.read_sql_query(
            "SELECT p.data, p.unidade, i.nome, i.categoria, ip.quantidade, ip.preco_unitario "
            "FROM itens_pedido ip JOIN itens i ON i.id = ip.item_id JOIN pedidos p ON p.id = ip.pedido_id "
            "WHERE p.status != 'cancelado'", con)
        aval = pd.read_sql_query("SELECT data, unidade, nota FROM avaliacoes", con)
    finally:
        con.close()
    for d in (ped, itens, aval):
        d["mes"] = d["data"].str[:7]
    return ped, itens, aval


def indicadores(ped: pd.DataFrame, aval: pd.DataFrame) -> dict:
    ent = ped[ped.status != "cancelado"]
    return {
        "fat": ent.valor_total.sum(), "pedidos": len(ent),
        "ticket": ent.valor_total.mean() if len(ent) else 0,
        "cancel": (ped.status == "cancelado").mean() * 100 if len(ped) else 0,
        "tempo": ent.tempo_entrega_min.mean() if len(ent) else 0,
        "nota": aval.nota.mean() if len(aval) else 0,
    }


def variacao_pct(atual: float, anterior: float) -> str | None:
    if not anterior:
        return None
    return f"{(atual / anterior - 1) * 100:+.1f}%".replace(".", ",")


def ponto_de_atencao(ped: pd.DataFrame, aval: pd.DataFrame, mes: str, anterior: str) -> str | None:
    """Unidade com a maior queda de faturamento do mês frente ao anterior (só se passar de 10%)."""
    pior = None
    for un in sorted(ped.unidade.unique()):
        a = indicadores(ped[(ped.mes == mes) & (ped.unidade == un)], aval[(aval.mes == mes) & (aval.unidade == un)])
        b = indicadores(ped[(ped.mes == anterior) & (ped.unidade == un)],
                        aval[(aval.mes == anterior) & (aval.unidade == un)])
        if not b["fat"]:
            continue
        queda = a["fat"] / b["fat"] - 1
        if queda < -0.10 and (pior is None or queda < pior[0]):
            pior = (queda, un, a, b)
    if not pior:
        return None
    queda, un, a, b = pior
    return (
        f"<b>Ponto de atenção · {un}, {NOME_MES[mes]}:</b> faturamento {queda * 100:+.1f}".replace(".", ",") + "% frente a "
        f"{NOME_MES[anterior]} ({brl(b['fat'])} → {brl(a['fat'])}); tempo de entrega "
        f"{num(b['tempo'])} → {num(a['tempo'])} min; cancelamentos {num(b['cancel'])}% → {num(a['cancel'])}%; "
        f"nota {num(b['nota'], 2)} → {num(a['nota'], 2)}."
    )


def mensal(df: pd.DataFrame, valor: str, agg: str = "mean") -> pd.DataFrame:
    g = df.groupby(["mes", "unidade"])[valor].agg(agg).reset_index()
    g["Mês"] = g["mes"].map(NOME_MES)
    return g.rename(columns={"unidade": "Unidade"})


def linha(df: pd.DataFrame, y: str, titulo: str, rotulo_y: str, intervalo=None):
    fig = px.line(df, x="Mês", y=y, color="Unidade", markers=True, title=titulo,
                  color_discrete_map=COR_UNIDADE, labels={y: rotulo_y})
    fig.update_traces(line=dict(width=3), marker=dict(size=8))
    if intervalo:
        fig.update_yaxes(range=intervalo)
    fig.update_xaxes(title_text="")
    return estilizar(fig)


def painel(cabecalho):
    """`cabecalho` é a função de título do app principal (mantém o mesmo visual das outras seções)."""
    st.markdown("<style>.block-container{max-width:1180px}</style>", unsafe_allow_html=True)
    cabecalho("Painel", "de <em>indicadores</em>",
              "Como o negócio vem se comportando mês a mês, por unidade. Dados sintéticos de jun a out/2026.")

    ped, itens, aval = carregar()
    c1, c2 = st.columns([2, 1])
    de, ate = c1.select_slider("Período", options=MESES, value=(MESES[0], MESES[-1]),
                               format_func=NOME_MES.get)
    unidades = c2.multiselect("Unidades", sorted(ped.unidade.unique()), default=sorted(ped.unidade.unique()))
    if not unidades:
        st.info("Selecione ao menos uma unidade.")
        return

    sel = MESES[MESES.index(de): MESES.index(ate) + 1]
    ped_f = ped[ped.mes.isin(sel) & ped.unidade.isin(unidades)]
    aval_f = aval[aval.mes.isin(sel) & aval.unidade.isin(unidades)]
    itens_f = itens[itens.mes.isin(sel) & itens.unidade.isin(unidades)]
    atual = indicadores(ped_f, aval_f)

    # período anterior com o mesmo número de meses (só existe se couber nos dados)
    ini = MESES.index(de)
    prev = MESES[ini - len(sel): ini] if ini - len(sel) >= 0 else []
    ant = None
    if prev:
        ant = indicadores(ped[ped.mes.isin(prev) & ped.unidade.isin(unidades)],
                          aval[aval.mes.isin(prev) & aval.unidade.isin(unidades)])

    def delta(chave, tipo="pct"):
        if not ant:
            return None
        if tipo == "pct":
            return variacao_pct(atual[chave], ant[chave])
        return f"{atual[chave] - ant[chave]:+.1f}".replace(".", ",") + (" p.p." if tipo == "pp" else " min")

    cartoes = [
        ("Faturamento", brl(atual["fat"]), delta("fat"), "normal"),
        ("Pedidos entregues", num(atual["pedidos"], 0), delta("pedidos"), "normal"),
        ("Ticket médio", "R$ " + num(atual["ticket"], 2), delta("ticket"), "normal"),
        ("Cancelamentos", num(atual["cancel"]) + "%", delta("cancel", "pp"), "inverse"),
        ("Tempo médio de entrega", num(atual["tempo"]) + " min", delta("tempo", "min"), "inverse"),
        ("Nota média", num(atual["nota"], 2), None if not ant else f"{atual['nota'] - ant['nota']:+.2f}".replace(".", ","),
         "normal"),
    ]
    for linha_cartoes in (cartoes[:3], cartoes[3:]):
        for col, (rotulo, valor, d, cor) in zip(st.columns(3), linha_cartoes):
            col.metric(rotulo, valor, d, delta_color=cor)
    if prev:
        st.caption(f"Variações em relação ao período anterior ({NOME_MES[prev[0]]} a {NOME_MES[prev[-1]]}).")
    else:
        st.caption("Sem período anterior para comparar: o recorte começa no primeiro mês dos dados.")

    # alerta automático: último mês do recorte frente ao mês anterior
    i_fim = MESES.index(ate)
    if i_fim > 0:
        msg = ponto_de_atencao(ped[ped.unidade.isin(unidades)], aval[aval.unidade.isin(unidades)],
                               MESES[i_fim], MESES[i_fim - 1])
        if msg:
            st.markdown(f'<div class="atencao">{msg}</div>', unsafe_allow_html=True)

    ent = ped_f[ped_f.status != "cancelado"]
    ped_f = ped_f.assign(cancelado=(ped_f.status == "cancelado") * 100)

    a, b = st.columns(2)
    fat = mensal(ent, "valor_total", "sum")
    fig = px.bar(fat, x="Mês", y="valor_total", color="Unidade", title="Faturamento por mês",
                 color_discrete_map=COR_UNIDADE, labels={"valor_total": "Faturamento (R$)"})
    fig.update_xaxes(title_text="")
    a.plotly_chart(estilizar(fig), width="stretch", key="d_fat", config=CONFIG)
    b.plotly_chart(linha(mensal(ent, "tempo_entrega_min"), "tempo_entrega_min", "Tempo médio de entrega (min)",
                         "Minutos"), width="stretch", key="d_tempo", config=CONFIG)

    a, b = st.columns(2)
    a.plotly_chart(linha(mensal(ped_f, "cancelado"), "cancelado", "Taxa de cancelamento (%)", "%"),
                   width="stretch", key="d_canc", config=CONFIG)
    b.plotly_chart(linha(mensal(aval_f, "nota"), "nota", "Nota média dos clientes", "Nota", intervalo=[1, 5]),
                   width="stretch", key="d_nota", config=CONFIG)

    a, b = st.columns([3, 2])
    top = (itens_f.assign(receita=itens_f.quantidade * itens_f.preco_unitario)
           .groupby("nome").receita.sum().nlargest(8).reset_index().sort_values("receita"))
    fig = px.bar(top, x="receita", y="nome", orientation="h", title="Itens que mais faturam",
                 color_discrete_sequence=[PALETA[0]], labels={"receita": "Receita (R$)", "nome": ""})
    a.plotly_chart(estilizar(fig), width="stretch", key="d_top", config=CONFIG)
    canal = ent.groupby("canal").size().reset_index(name="pedidos")
    canal["canal"] = canal.canal.map({"app_proprio": "App próprio", "marketplace": "Marketplace"}).fillna(canal.canal)
    fig = px.pie(canal, names="canal", values="pedidos", hole=0.55, title="Pedidos por canal",
                 color_discrete_sequence=[PALETA[0], PALETA[1]])
    fig.update_traces(textinfo="percent", textfont_size=14)
    b.plotly_chart(estilizar(fig), width="stretch", key="d_canal", config=CONFIG)

    calor = (ent.groupby(["dia_semana", "hora"]).size().unstack(fill_value=0)
             .reindex(DIAS).fillna(0))
    fig = px.imshow(calor, aspect="auto", title="Quando os pedidos acontecem (dia da semana × hora)",
                    color_continuous_scale=["#FFFAF0", "#F0B323", "#1F8A4C"],
                    labels=dict(x="Hora do dia", y="", color="Pedidos"))
    fig.update_xaxes(side="bottom", dtick=1)
    st.plotly_chart(estilizar(fig, 380), width="stretch", key="d_calor", config=CONFIG)
