"""
Triagem de avaliações: classifica comentários (sentimento, tema, urgência), resume
os problemas mais frequentes e sugere respostas para o restaurante publicar.
"""

import os
from typing import Literal

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel

from agente.agente import MODELO, RAIZ

load_dotenv(RAIZ / ".env")

MAX_AVALIACOES = 40
TEMAS = ["atraso na entrega", "comida fria", "qualidade da comida", "pedido errado ou incompleto",
         "embalagem", "atendimento", "preço", "elogio", "outro"]


class ItemTriagem(BaseModel):
    id: int
    sentimento: Literal["positivo", "neutro", "negativo"]
    tema: str
    urgencia: Literal["baixa", "media", "alta"]


class ResultadoTriagem(BaseModel):
    resumo: str
    itens: list[ItemTriagem]


def _cliente(cliente=None):
    return cliente or genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


def triar(avaliacoes: list[dict], cliente=None) -> ResultadoTriagem:
    """avaliacoes: [{'id', 'unidade', 'nota', 'comentario'}, ...]. Classifica e resume."""
    avaliacoes = avaliacoes[:MAX_AVALIACOES]
    texto = "\n".join(
        f"[{a['id']}] unidade={a['unidade']} nota={a['nota']}: {a['comentario']}" for a in avaliacoes
    )
    prompt = (
        "Você analisa avaliações de clientes de um restaurante delivery. Para CADA avaliação, "
        f"devolva sentimento, tema (prefira um destes: {', '.join(TEMAS)}) e urgência "
        "(alta = problema grave que pode perder o cliente; média; baixa = elogio ou detalhe). "
        "Depois escreva um resumo de 2 a 3 frases em português do Brasil, apontando os problemas "
        "mais frequentes e as unidades mais afetadas. Use exatamente os ids fornecidos.\n\n" + texto
    )
    cliente = _cliente(cliente)
    resp = cliente.models.generate_content(
        model=MODELO,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json", response_schema=ResultadoTriagem
        ),
    )
    if resp.parsed is None:
        raise ValueError("O modelo não devolveu uma classificação válida.")
    return resp.parsed


def sugerir_resposta(unidade: str, nota: int, comentario: str, cliente=None) -> str:
    """Rascunho de resposta pública, educada e sem prometer o que o restaurante não pode cumprir."""
    prompt = (
        f'Escreva a resposta do restaurante "Sabor da Casa" (unidade {unidade}) a esta avaliação '
        f"de {nota} estrela(s): \"{comentario}\"\n\n"
        "Regras: português do Brasil, tom cordial e humano, 2 a 4 frases, peça desculpas só se houve "
        "problema, mencione o ponto específico do cliente, não prometa reembolso, desconto, brinde, novo pedido nem prazos, "
        "e termine agradecendo o feedback. Devolva só o texto da resposta."
    )
    cliente = _cliente(cliente)
    resp = cliente.models.generate_content(model=MODELO, contents=prompt)
    return (resp.text or "").strip()
