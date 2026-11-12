"""Copiloto do Restaurante: chat analítico + triagem de avaliações.

Rodar com:  streamlit run app.py
"""

import sqlite3
import threading
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from agente.agente import BANCO, perguntar
from agente.triagem import MAX_AVALIACOES, sugerir_resposta, triar

st.set_page_config(page_title="Copiloto do Restaurante", page_icon="🍽️", layout="centered")

RAIZ = Path(__file__).resolve().parent
st.markdown(f"<style>{(RAIZ / 'estilo.css').read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)

SUGESTOES = [
    "Como foram as vendas de outubro comparado a setembro?",
    "Por que o faturamento caiu em outubro?",
    "Qual unidade tem a melhor nota dos clientes?",
    "Quais são os 5 itens mais vendidos?",
    "Como estão os cancelamentos por unidade?",
]
PALETA = ["#1F8A4C", "#EDA417", "#2B63B0", "#D93F77", "#E8742C", "#4F5F57"]
MESES = {"Todos": None, "Jun/2026": "2026-06", "Jul/2026": "2026-07", "Ago/2026": "2026-08",
         "Set/2026": "2026-09", "Out/2026": "2026-10"}

# --- Limite de uso (protege a cota gratuita do Gemini num app público) ---------------------
LIMITE_SESSAO = 15  # chamadas de IA por visitante
LIMITE_DIARIO = 300  # chamadas de IA por dia, somando todos os visitantes


@st.cache_resource
def _contador_global():
    return {"dia": date.today(), "n": 0, "lock": threading.Lock()}


def reservar_uso() -> str | None:
    """Conta uma chamada de IA. Devolve uma mensagem de bloqueio, ou None se está liberado."""
    if st.session_state.usos >= LIMITE_SESSAO:
        return (f"Você atingiu o limite de {LIMITE_SESSAO} consultas desta demonstração. "
                "Atualize a página para recomeçar ou fale comigo para ver mais! 🙂")
    g = _contador_global()
    with g["lock"]:
        if g["dia"] != date.today():
            g["dia"], g["n"] = date.today(), 0
        if g["n"] >= LIMITE_DIARIO:
            return "A demonstração atingiu o limite de uso de hoje. Volte amanhã! 🙂"
        g["n"] += 1
    st.session_state.usos += 1
    return None


# --- Dados ----------------------------------------------------------------------------------
def _conectar():
    return sqlite3.connect(f"file:{BANCO}?mode=ro", uri=True)


@st.cache_data(ttl=600)
def indicadores():
    """KPIs de outubro/2026 (último mês dos dados) para a barra lateral."""
    con = _conectar()
    try:
        fat, ped = con.execute(
            "SELECT SUM(valor_total), COUNT(*) FROM pedidos "
            "WHERE status != 'cancelado' AND data LIKE '2026-10%'"
        ).fetchone()
        canc = con.execute(
            "SELECT AVG(status = 'cancelado') FROM pedidos WHERE data LIKE '2026-10%'"
        ).fetchone()[0]
        nota = con.execute("SELECT AVG(nota) FROM avaliacoes WHERE data LIKE '2026-10%'").fetchone()[0]
    finally:
        con.close()
    return fat or 0, ped or 0, canc or 0, nota or 0


@st.cache_data(ttl=600)
def carregar_avaliacoes() -> pd.DataFrame:
    con = _conectar()
    try:
        return pd.read_sql_query(
            "SELECT id, data, unidade, nota, comentario FROM avaliacoes ORDER BY data DESC, id DESC", con
        )
    finally:
        con.close()


def brl(v: float) -> str:
    return "R$ " + f"{v:,.0f}".replace(",", ".")


# --- Componentes ----------------------------------------------------------------------------
def mostrar_sqls(sqls):
    if sqls:
        with st.expander(f"🔎 Ver como cheguei nisso ({len(sqls)} consulta(s))"):
            for s in sqls:
                st.code(s, language="sql")


def mostrar_grafico(g: dict, chave: str):
    df = pd.DataFrame(g["dados"])
    cor = g.get("cor")
    rotulo = lambda c: str(c).replace("_", " ").capitalize()  # noqa: E731
    args = dict(x=g["x"], y=g["y"], color=cor, title=g["titulo"], color_discrete_sequence=PALETA,
                labels={c: rotulo(c) for c in df.columns})
    if g["tipo"] == "linha":
        fig = px.line(df, markers=True, **args)
    else:
        fig = px.bar(df, barmode="group", text_auto=".3s", **args)
    if df[g["x"]].dtype == object or g["tipo"] == "barra":
        fig.update_xaxes(type="category")  # evita eixo contínuo com datas "soltas"
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=50, b=10), legend_title_text="", yaxis_gridcolor="#E5D6B6",
        font=dict(family="Inter, sans-serif", color="#17332E"),
    )
    st.plotly_chart(fig, width="stretch", key=chave, config={"displayModeBar": False})


def cabecalho(linha1: str, destaque: str, texto: str):
    st.markdown(
        f'<h1 class="titulo">{linha1}<br>{destaque}</h1><p class="lead">{texto}</p>',
        unsafe_allow_html=True,
    )


def estrelas(nota: float) -> str:
    """5 estrelas em SVG, preenchidas até `nota` (0 a 5)."""
    poly = "9,1 11.06,6.17 16.61,6.53 12.33,10.08 13.7,15.47 9,12.5 4.3,15.47 5.67,10.08 1.39,6.53 6.94,6.17"
    estrela = "".join(f'<polygon points="{poly}" transform="translate({20 * i} 0)"/>' for i in range(5))
    largura = max(0.0, min(nota / 5, 1.0)) * 98
    return (
        f'<svg width="98" height="18" viewBox="0 0 98 18" role="img" aria-label="Nota {nota:.2f} de 5">'
        f'<defs><g id="estrelas">{estrela}</g><clipPath id="corte"><rect width="{largura:.1f}" height="18"/></clipPath></defs>'
        '<use href="#estrelas" fill="#4F8A7D"/><use href="#estrelas" clip-path="url(#corte)" fill="#F2B01E"/></svg>'
    )


def barra_lateral_kpis() -> str:
    fat, ped, canc, nota = indicadores()
    pedidos = f"{ped:,}".replace(",", ".")
    cancel = f"{canc:.1%}".replace(".", ",")
    nota_txt = f"{nota:.2f}".replace(".", ",")
    return (
        '<div class="kpi-hero"><div class="l">Faturamento</div>'
        f'<div class="v"><small>R$</small><b>{fat:,.0f}</b></div></div>'.replace(",", ".")
        + '<div class="kpi-lista">'
        f'<div class="linha"><span>Pedidos entregues</span><strong>{pedidos}</strong></div>'
        f'<div class="linha"><span>Cancelamentos</span><strong>{cancel}</strong></div>'
        f'<div class="linha"><span>Nota média</span><strong>{estrelas(nota)}{nota_txt}</strong></div>'
        "</div>"
    )


# --- Estado e barra lateral -----------------------------------------------------------------
st.session_state.setdefault("mensagens", [])  # histórico exibido
st.session_state.setdefault("historico", [])  # histórico da API
st.session_state.setdefault("usos", 0)

LOGO = (
    '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" '
    'aria-hidden="true"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4.5"/></svg>'
)
CALENDARIO = (
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#F2B01E" stroke-width="1.8" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="5" width="16" '
    'height="15" rx="3"/><path d="M4 10h16M8 3v4M16 3v4"/></svg>'
)

with st.sidebar:
    st.markdown(
        f'<div class="marca"><div class="logo">{LOGO}</div><div><div class="nome">Sabor da Casa</div>'
        '<div class="sub">Centro · Pinheiros · Vila Nova</div></div></div>',
        unsafe_allow_html=True,
    )
    pagina = st.radio("Seção", ["💬 Chat com o analista", "🧾 Triagem de avaliações"],
                      label_visibility="collapsed")
    st.markdown(
        f'<div class="rotulo" style="margin-top:18px">Período</div>'
        f'<div class="periodo">{CALENDARIO}<span>Outubro/2026</span></div>',
        unsafe_allow_html=True,
    )
    try:
        st.markdown(barra_lateral_kpis(), unsafe_allow_html=True)
    except Exception:
        st.caption("Indicadores indisponíveis.")
    if pagina.startswith("💬") and st.button("Nova conversa", width="stretch"):
        st.session_state.mensagens = []
        st.session_state.historico = []
        st.rerun()
    st.caption(f"Consultas de IA restantes: {max(LIMITE_SESSAO - st.session_state.usos, 0)}")
    st.caption("Dados sintéticos de jun–out/2026. Feito com Streamlit + Gemini.")


# --- Página: chat ---------------------------------------------------------------------------
def pagina_chat():
    cabecalho("Copiloto", "do <em>Restaurante</em>",
              "Seu analista de dados particular. Pergunte em português sobre vendas, pedidos, "
              "entregas e avaliações.")

    pergunta = None
    if not st.session_state.mensagens:
        st.markdown('<div class="rotulo">Experimente perguntar</div>', unsafe_allow_html=True)
        with st.container(key="sugestoes"):
            for i, texto_sug in enumerate(SUGESTOES):
                if st.button(texto_sug, key=f"sug{i}", width="stretch"):
                    pergunta = texto_sug

    for i, m in enumerate(st.session_state.mensagens):
        with st.chat_message(m["role"], avatar="🧑‍🍳" if m["role"] == "user" else "🤖"):
            st.markdown(m["texto"])
            for j, g in enumerate(m.get("graficos") or []):
                mostrar_grafico(g, f"g{i}_{j}")
            mostrar_sqls(m.get("sqls"))

    pergunta = st.chat_input("Ex.: por que as vendas do Centro caíram em outubro?") or pergunta
    if not pergunta:
        return

    st.session_state.mensagens.append({"role": "user", "texto": pergunta})
    with st.chat_message("user", avatar="🧑‍🍳"):
        st.markdown(pergunta)
    with st.chat_message("assistant", avatar="🤖"):
        sqls, graficos = [], []
        bloqueio = reservar_uso()
        if bloqueio:
            texto = bloqueio
        else:
            with st.spinner("Analisando os dados do restaurante..."):
                try:
                    texto, hist, sqls, graficos = perguntar(pergunta, st.session_state.historico)
                    st.session_state.historico = hist
                except Exception as e:
                    texto = (
                        "😕 Não consegui responder agora. O serviço de IA pode estar "
                        "sobrecarregado, tente de novo em instantes.\n\n"
                        f"<sub>Detalhe técnico: {str(e)[:200]}</sub>"
                    )
        st.markdown(texto, unsafe_allow_html=True)
        for j, g in enumerate(graficos):
            mostrar_grafico(g, f"novo_{len(st.session_state.mensagens)}_{j}")
        mostrar_sqls(sqls)
    st.session_state.mensagens.append(
        {"role": "assistant", "texto": texto, "sqls": sqls, "graficos": graficos}
    )
    st.rerun()


# --- Página: triagem de avaliações ----------------------------------------------------------
def pagina_avaliacoes():
    cabecalho("Triagem", "de <em>avaliações</em>",
              "A IA classifica as avaliações dos clientes, resume os problemas e sugere respostas.")
    df = carregar_avaliacoes()

    c1, c2, c3 = st.columns([2, 1.2, 1.2])
    unidades = c1.multiselect("Unidades", sorted(df["unidade"].unique()),
                              default=sorted(df["unidade"].unique()))
    mes = c2.selectbox("Mês", list(MESES), index=len(MESES) - 1)
    nota_max = c3.slider("Nota até", 1, 5, 2)

    f = df[df["unidade"].isin(unidades) & (df["nota"] <= nota_max)]
    if MESES[mes]:
        f = f[f["data"].str.startswith(MESES[mes])]
    f = f.head(MAX_AVALIACOES)

    m1, m2 = st.columns(2)
    m1.metric("Avaliações selecionadas", len(f))
    m2.metric("Nota média", f"{f['nota'].mean():.2f}".replace(".", ",") if len(f) else "–")
    st.caption(f"A análise considera as {MAX_AVALIACOES} avaliações mais recentes do filtro.")

    if f.empty:
        st.info("Nenhuma avaliação com esses filtros.")
        return

    if st.button("✨ Analisar com IA", width="stretch"):
        bloqueio = reservar_uso()
        if bloqueio:
            st.warning(bloqueio)
        else:
            with st.spinner("Lendo e classificando as avaliações..."):
                try:
                    res = triar(f.to_dict("records"))
                    st.session_state.triagem = {"resultado": res, "base": f.copy()}
                except Exception as e:
                    st.error(f"Não consegui analisar agora, tente de novo em instantes. ({str(e)[:150]})")

    t = st.session_state.get("triagem")
    if not t:
        st.dataframe(f[["data", "unidade", "nota", "comentario"]], hide_index=True,
                     width="stretch")
        return

    st.info(t["resultado"].resumo, icon="💡")
    classif = pd.DataFrame([i.model_dump() for i in t["resultado"].itens])
    tab = t["base"].merge(classif, on="id", how="inner")
    ordem = {"alta": 0, "media": 1, "baixa": 2}
    tab = tab.sort_values("urgencia", key=lambda s: s.map(ordem))

    temas = tab["tema"].value_counts().reset_index()
    temas.columns = ["tema", "avaliações"]
    fig = px.bar(temas, x="avaliações", y="tema", orientation="h", title="Temas mais citados",
                 color_discrete_sequence=PALETA)
    fig.update_layout(yaxis=dict(autorange="reversed"), paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)", margin=dict(l=10, r=10, t=50, b=10), yaxis_title="",
                      font=dict(family="Inter, sans-serif", color="#17332E"))
    st.plotly_chart(fig, width="stretch", key="temas", config={"displayModeBar": False})

    st.dataframe(
        tab[["urgencia", "sentimento", "tema", "unidade", "nota", "comentario"]],
        hide_index=True, width="stretch",
    )

    st.markdown("#### ✍️ Responder um cliente")
    rotulos = {r.id: f"#{r.id} · {r.unidade} · {r.nota}⭐ · {r.comentario[:70]}"
               for r in tab.itertuples()}
    escolhido = st.selectbox("Avaliação", list(rotulos), format_func=rotulos.get)
    if st.button("Sugerir resposta"):
        bloqueio = reservar_uso()
        if bloqueio:
            st.warning(bloqueio)
        else:
            linha = tab[tab["id"] == escolhido].iloc[0]
            with st.spinner("Escrevendo uma resposta..."):
                try:
                    st.session_state.resposta = sugerir_resposta(
                        linha["unidade"], int(linha["nota"]), linha["comentario"]
                    )
                    st.session_state.resposta_id = escolhido
                except Exception as e:
                    st.error(f"Não consegui gerar a resposta agora. ({str(e)[:150]})")
    if st.session_state.get("resposta") and st.session_state.get("resposta_id") == escolhido:
        st.text_area("Rascunho (edite antes de publicar)", st.session_state.resposta, height=140)


if pagina.startswith("💬"):
    pagina_chat()
else:
    pagina_avaliacoes()
