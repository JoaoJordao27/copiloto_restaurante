"""
Agente de análise: responde perguntas em português consultando o banco SQLite.

O Gemini recebe uma ferramenta `consultar_sql` (somente leitura), escreve as
consultas, lê os resultados e responde ao dono do restaurante.

Uso rápido:  python agente/agente.py "Como foram as vendas de outubro?"
"""

import os
import sqlite3
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from google import genai
from google.genai import types

RAIZ = Path(__file__).resolve().parent.parent
BANCO = RAIZ / "dados" / "restaurante.db"
MODELO = os.getenv("MODELO_GEMINI", "gemini-3.5-flash-lite")
MAX_LINHAS = 200
MAX_RODADAS = 12

load_dotenv(RAIZ / ".env")

SISTEMA = """Você é o Copiloto do Restaurante, analista de dados do dono do restaurante \
delivery "Sabor da Casa" (3 unidades: Centro, Pinheiros, Vila Nova).

Regras:
- Responda sempre em português do Brasil, de forma direta e sem jargão técnico.
- Para qualquer número, consulte o banco com a ferramenta consultar_sql. Nunca invente valores.
- Ao analisar vendas, desconsidere pedidos com status 'cancelado' no faturamento, \
mas use-os ao falar de cancelamentos.
- Quando a pergunta for aberta ("o que aconteceu?"), investigue: compare períodos, \
unidades, tempo de entrega, cancelamentos e comentários das avaliações antes de concluir.
- Quando uma comparação ou evolução ficar mais clara visualmente (ex.: faturamento por mês, \
por unidade, itens mais vendidos), use a ferramenta criar_grafico (no máximo 2 gráficos por \
resposta). O gráfico aparece para o usuário automaticamente; não descreva o código dele.
- Termine com a conclusão e, se fizer sentido, uma sugestão prática de ação.
- Dados disponíveis: de 2026-06-01 a 2026-10-31.

Esquema do banco (SQLite):
- itens(id, nome, categoria, preco, custo)
- pedidos(id, data_hora, data 'YYYY-MM-DD', hora, dia_semana, unidade, canal, status, \
valor_itens, taxa_entrega, valor_total, tempo_entrega_min)
- itens_pedido(pedido_id, item_id, quantidade, preco_unitario)
- avaliacoes(id, pedido_id, data, unidade, nota 1-5, comentario)
"""

FERRAMENTA = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="consultar_sql",
            description="Executa uma consulta SELECT (somente leitura) no banco do restaurante "
            f"e devolve até {MAX_LINHAS} linhas.",
            parameters=types.Schema(
                type="OBJECT",
                properties={"sql": types.Schema(type="STRING", description="Consulta SELECT em SQLite.")},
                required=["sql"],
            ),
        ),
        types.FunctionDeclaration(
            name="criar_grafico",
            description="Mostra um gráfico ao usuário a partir de uma consulta SELECT. "
            "As colunas x e y precisam existir no resultado. Use aliases descritivos em português "
            "(ex.: mes, unidade, faturamento), nunca 'x' ou 'y'. Para comparar períodos ou grupos, "
            "prefira uma linha por barra/ponto e use `cor` para separar as séries.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "sql": types.Schema(type="STRING", description="Consulta SELECT em SQLite."),
                    "tipo": types.Schema(type="STRING", enum=["barra", "linha"]),
                    "x": types.Schema(type="STRING", description="Coluna do eixo X."),
                    "y": types.Schema(
                        type="STRING",
                        description="Coluna numérica do eixo Y. Pode listar várias separadas por vírgula "
                        "(ex.: setembro,outubro) para comparar colunas lado a lado.",
                    ),
                    "titulo": types.Schema(type="STRING", description="Título do gráfico em português."),
                    "cor": types.Schema(
                        type="STRING", description="(opcional) Coluna que separa séries, ex.: unidade."
                    ),
                },
                required=["sql", "tipo", "x", "y", "titulo"],
            ),
        ),
    ]
)


def consultar_df(sql: str) -> pd.DataFrame:
    """Roda um SELECT somente leitura e devolve um DataFrame (levanta ValueError se inválido)."""
    if not sql.strip().lower().startswith(("select", "with")):
        raise ValueError("apenas consultas SELECT são permitidas.")
    con = sqlite3.connect(f"file:{BANCO}?mode=ro", uri=True)
    try:
        return pd.read_sql_query(sql, con).head(MAX_LINHAS)
    except Exception as e:  # erro SQL
        raise ValueError(str(e)) from e
    finally:
        con.close()


def executar_sql(sql: str) -> str:
    """Roda a consulta em modo somente leitura e devolve o resultado como texto."""
    try:
        df = consultar_df(sql)
    except ValueError as e:
        return f"Erro SQL: {e}"
    if df.empty:
        return "(nenhuma linha)"
    linhas = [" | ".join(map(str, l)) for l in df.itertuples(index=False)]
    return "\n".join([" | ".join(df.columns)] + linhas)


def montar_grafico(args: dict) -> tuple[str, dict | None]:
    """Valida os argumentos de criar_grafico. Devolve (mensagem para o modelo, especificação)."""
    try:
        df = consultar_df(args.get("sql", ""))
    except ValueError as e:
        return f"Erro SQL: {e}", None
    x, cor = args.get("x"), args.get("cor") or None
    ys = [c.strip() for c in str(args.get("y", "")).split(",") if c.strip()]
    faltando = [c for c in [x, cor, *ys] if c and c not in df.columns]
    if df.empty or faltando:
        motivo = faltando or "resultado vazio"
        return f"Não foi possível criar o gráfico ({motivo}). Colunas: {list(df.columns)}", None
    if len(ys) > 1 and not cor:  # várias colunas de valor -> formato longo, uma série por coluna
        df = df.melt(id_vars=x, value_vars=ys, var_name="série", value_name="valor")
        ys, cor = ["valor"], "série"
    y = ys[0]
    spec = {
        "tipo": args.get("tipo", "barra"), "x": x, "y": y, "cor": cor,
        "titulo": args.get("titulo", ""), "dados": df.to_dict("records"),
    }
    return "Gráfico exibido ao usuário.", spec


def perguntar(pergunta: str, historico: list | None = None, cliente=None):
    """Responde a uma pergunta. Devolve (texto, historico_atualizado, consultas_sql, graficos)."""
    cliente = cliente or genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    config = types.GenerateContentConfig(
        system_instruction=SISTEMA,
        tools=[FERRAMENTA],
        max_output_tokens=2000,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    conteudos = list(historico or []) + [
        types.Content(role="user", parts=[types.Part.from_text(text=pergunta)])
    ]
    consultas, graficos = [], []

    for _ in range(MAX_RODADAS):
        resp = cliente.models.generate_content(model=MODELO, contents=conteudos, config=config)
        if not resp.candidates or not resp.candidates[0].content:
            return "O modelo não devolveu resposta. Tente reformular a pergunta.", conteudos, consultas, graficos
        conteudos.append(resp.candidates[0].content)
        chamadas = resp.function_calls or []
        if not chamadas:
            return resp.text or "", conteudos, consultas, graficos

        partes = []
        for chamada in chamadas:
            args = dict(chamada.args or {})
            consultas.append(args.get("sql", ""))
            if chamada.name == "criar_grafico":
                resultado, spec = montar_grafico(args)
                if spec:
                    graficos.append(spec)
            else:
                resultado = executar_sql(args.get("sql", ""))
            partes.append(
                types.Part.from_function_response(name=chamada.name, response={"resultado": resultado})
            )
        conteudos.append(types.Content(role="user", parts=partes))

    return "Não consegui concluir a análise dentro do limite de consultas.", conteudos, consultas, graficos


if __name__ == "__main__":
    pergunta = " ".join(sys.argv[1:]) or "Como foram as vendas de outubro comparado a setembro?"
    texto, _, sqls, _ = perguntar(pergunta)
    print(texto)
    print(f"\n[{len(sqls)} consulta(s) SQL executada(s)]")
