"""Chat do Copiloto do Restaurante.  Rodar com:  streamlit run app.py"""

import sqlite3

import streamlit as st

from agente.agente import BANCO, perguntar

st.set_page_config(page_title="Copiloto do Restaurante", page_icon="🍽️", layout="centered")

st.markdown(
    """
    <style>
    #MainMenu, footer {visibility: hidden;}
    .block-container {padding-top: 2rem; max-width: 820px;}
    .hero {
        background: linear-gradient(135deg, #E8590C 0%, #F59F00 100%);
        color: white; padding: 1.6rem 1.8rem; border-radius: 20px;
        margin-bottom: 1.2rem; box-shadow: 0 8px 24px rgba(232, 89, 12, .25);
    }
    .hero h1 {margin: 0; font-size: 1.9rem; color: white;}
    .hero p {margin: .3rem 0 0 0; opacity: .95; font-size: 1rem;}
    [data-testid="stChatMessage"] {
        background: white; border-radius: 16px; padding: 1rem 1.2rem;
        box-shadow: 0 2px 10px rgba(0, 0, 0, .06); margin-bottom: .8rem;
    }
    div.stButton > button {
        border-radius: 999px; border: 1px solid #E8590C; color: #E8590C;
        background: white; text-align: left; transition: all .15s;
    }
    div.stButton > button:hover {background: #E8590C; color: white;}
    [data-testid="stSidebar"] {background: #FFF0E3;}
    [data-testid="stMetric"] {
        background: white; padding: .7rem .9rem; border-radius: 14px;
        box-shadow: 0 2px 8px rgba(0, 0, 0, .05);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

SUGESTOES = [
    "Como foram as vendas de outubro comparado a setembro?",
    "Por que o faturamento caiu em outubro?",
    "Qual unidade tem a melhor nota dos clientes?",
    "Quais são os 5 itens mais vendidos?",
    "Como estão os cancelamentos por unidade?",
]


@st.cache_data(ttl=600)
def indicadores():
    """KPIs de outubro/2026 (último mês dos dados) para a barra lateral."""
    con = sqlite3.connect(f"file:{BANCO}?mode=ro", uri=True)
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


def brl(v: float) -> str:
    return "R$ " + f"{v:,.0f}".replace(",", ".")


def mostrar_sqls(sqls):
    if sqls:
        with st.expander(f"🔎 Ver como cheguei nisso ({len(sqls)} consulta(s))"):
            for s in sqls:
                st.code(s, language="sql")


st.session_state.setdefault("mensagens", [])  # histórico exibido
st.session_state.setdefault("historico", [])  # histórico da API

with st.sidebar:
    st.markdown("### 🍽️ Sabor da Casa")
    st.caption("Centro · Pinheiros · Vila Nova")
    try:
        fat, ped, canc, nota = indicadores()
        st.markdown("**Outubro/2026**")
        st.metric("Faturamento", brl(fat))
        st.metric("Pedidos entregues", f"{ped:,}".replace(",", "."))
        st.metric("Cancelamentos", f"{canc:.1%}".replace(".", ","))
        st.metric("Nota média", f"{nota:.2f} ⭐".replace(".", ","))
    except Exception:
        st.caption("Indicadores indisponíveis.")
    st.divider()
    if st.button("🧹 Nova conversa", use_container_width=True):
        st.session_state.mensagens = []
        st.session_state.historico = []
        st.rerun()
    st.caption("Dados sintéticos de jun–out/2026. Feito com Streamlit + Gemini.")

st.markdown(
    """
    <div class="hero">
        <h1>🍽️ Copiloto do Restaurante</h1>
        <p>Seu analista de dados particular. Pergunte em português sobre vendas,
        pedidos, entregas e avaliações.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

pergunta = None
if not st.session_state.mensagens:
    st.markdown("**Experimente perguntar:**")
    for i, s in enumerate(SUGESTOES):
        if st.button(s, key=f"sug{i}", use_container_width=True):
            pergunta = s

for m in st.session_state.mensagens:
    with st.chat_message(m["role"], avatar="🧑‍🍳" if m["role"] == "user" else "🤖"):
        st.markdown(m["texto"])
        mostrar_sqls(m.get("sqls"))

pergunta = st.chat_input("Ex.: por que as vendas do Centro caíram em outubro?") or pergunta

if pergunta:
    st.session_state.mensagens.append({"role": "user", "texto": pergunta})
    with st.chat_message("user", avatar="🧑‍🍳"):
        st.markdown(pergunta)
    with st.chat_message("assistant", avatar="🤖"):
        with st.spinner("Analisando os dados do restaurante..."):
            try:
                texto, hist, sqls = perguntar(pergunta, st.session_state.historico)
                st.session_state.historico = hist
            except Exception as e:
                texto = (
                    "😕 Não consegui responder agora. O serviço de IA pode estar "
                    "sobrecarregado, tente de novo em instantes.\n\n"
                    f"<sub>Detalhe técnico: {str(e)[:200]}</sub>"
                )
                sqls = []
        st.markdown(texto, unsafe_allow_html=True)
        mostrar_sqls(sqls)
    st.session_state.mensagens.append({"role": "assistant", "texto": texto, "sqls": sqls})
    if len(st.session_state.mensagens) == 2:
        st.rerun()
