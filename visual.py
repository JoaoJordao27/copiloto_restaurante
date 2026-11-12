"""Estilo compartilhado dos gráficos (cores e fonte combinando com o resto do app)."""

PALETA = ["#1F8A4C", "#EDA417", "#2B63B0", "#D93F77", "#E8742C", "#4F5F57"]
COR_UNIDADE = {"Centro": "#1F8A4C", "Pinheiros": "#EDA417", "Vila Nova": "#2B63B0"}
FONTE = "Inter, sans-serif"


def estilizar(fig, altura: int = 340):
    """Fundo transparente, fonte Inter, legenda embaixo e grade discreta."""
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", height=altura,
        margin=dict(l=10, r=10, t=56, b=10), font=dict(family=FONTE, color="#17332E"),
        legend=dict(orientation="h", y=-0.2, x=0, title_text=""),
        title=dict(font=dict(size=15), x=0, xanchor="left"),
    )
    fig.update_yaxes(gridcolor="#E5D6B6", zeroline=False)
    fig.update_xaxes(showgrid=False)
    return fig


def brl(valor: float) -> str:
    return "R$ " + f"{valor:,.0f}".replace(",", ".")


def num(valor: float, casas: int = 1) -> str:
    """Número no formato brasileiro (vírgula decimal, ponto de milhar)."""
    return f"{valor:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
