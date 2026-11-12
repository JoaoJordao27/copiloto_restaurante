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

from dotenv import load_dotenv
from google import genai
from google.genai import types

RAIZ = Path(__file__).resolve().parent.parent
BANCO = RAIZ / "dados" / "restaurante.db"
MODELO = os.getenv("MODELO_GEMINI", "gemini-3.5-flash-lite")
MAX_LINHAS = 200
MAX_RODADAS = 8

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
        )
    ]
)


def executar_sql(sql: str) -> str:
    """Roda a consulta em modo somente leitura e devolve o resultado como texto."""
    if not sql.strip().lower().startswith(("select", "with")):
        return "Erro: apenas consultas SELECT são permitidas."
    try:
        con = sqlite3.connect(f"file:{BANCO}?mode=ro", uri=True)
        try:
            cur = con.execute(sql)
            colunas = [c[0] for c in cur.description]
            linhas = cur.fetchmany(MAX_LINHAS)
        finally:
            con.close()
    except sqlite3.Error as e:
        return f"Erro SQL: {e}"
    if not linhas:
        return "(nenhuma linha)"
    return "\n".join([" | ".join(colunas)] + [" | ".join(map(str, l)) for l in linhas])


def perguntar(pergunta: str, historico: list | None = None, cliente=None):
    """Responde a uma pergunta. Devolve (texto, historico_atualizado, consultas_sql)."""
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
    consultas = []

    for _ in range(MAX_RODADAS):
        resp = cliente.models.generate_content(model=MODELO, contents=conteudos, config=config)
        if not resp.candidates or not resp.candidates[0].content:
            return "O modelo não devolveu resposta. Tente reformular a pergunta.", conteudos, consultas
        conteudos.append(resp.candidates[0].content)
        chamadas = resp.function_calls or []
        if not chamadas:
            return resp.text or "", conteudos, consultas

        partes = []
        for chamada in chamadas:
            sql = (chamada.args or {}).get("sql", "")
            consultas.append(sql)
            partes.append(
                types.Part.from_function_response(
                    name=chamada.name, response={"resultado": executar_sql(sql)}
                )
            )
        conteudos.append(types.Content(role="user", parts=partes))

    return "Não consegui concluir a análise dentro do limite de consultas.", conteudos, consultas


if __name__ == "__main__":
    pergunta = " ".join(sys.argv[1:]) or "Como foram as vendas de outubro comparado a setembro?"
    texto, _, sqls = perguntar(pergunta)
    print(texto)
    print(f"\n[{len(sqls)} consulta(s) SQL executada(s)]")
