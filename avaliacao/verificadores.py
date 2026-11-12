"""Verificadores automáticos: decidem se a resposta do agente está correta, sem usar outro LLM."""

import re
import unicodedata
from dataclasses import dataclass, field

_TOKEN = re.compile(r"\d[\d.]*(?:,\d+)?")
_SUFIXO = re.compile(r"\s*(mil(?:h[ãa]o|h[õo]es)?|%)", re.IGNORECASE)


def normalizar(texto: str) -> str:
    """Minúsculas e sem acentos, para comparar palavras sem se preocupar com grafia."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sem_acento.lower()


def numeros(texto: str) -> list[float]:
    """Extrai todos os números do texto em formato brasileiro (1.234,56 | 152,2 mil | 4,6%)."""
    achados = []
    for m in _TOKEN.finditer(texto):
        bruto = m.group().rstrip(".")
        if not bruto:
            continue
        if "," in bruto:
            valor = float(bruto.replace(".", "").replace(",", "."))
        elif "." in bruto:
            partes = bruto.split(".")
            milhar = all(len(p) == 3 for p in partes[1:])
            valor = float(bruto.replace(".", "")) if milhar else float(bruto)
        else:
            valor = float(bruto)
        suf = _SUFIXO.match(texto, m.end())
        if suf and suf.group(1).lower().startswith("mil"):
            valor *= 1_000_000 if suf.group(1).lower().startswith("milh") else 1_000
        achados.append(valor)
    return achados


def contem_numero(texto: str, esperado: float, tol_rel: float = 0.005, tol_abs: float = 0.0) -> bool:
    margem = max(abs(esperado) * tol_rel, tol_abs)
    return any(abs(v - esperado) <= margem for v in numeros(texto))


@dataclass
class Caso:
    id: str
    categoria: str
    pergunta: str
    numeros: list = field(default_factory=list)  # [(valor, tol_rel, tol_abs)] todos obrigatórios
    numeros_alguma: list = field(default_factory=list)  # basta um destes
    todas: list = field(default_factory=list)  # palavras que precisam aparecer
    alguma: list = field(default_factory=list)  # basta uma destas palavras
    proibidas: list = field(default_factory=list)  # não podem aparecer
    exige_sql: bool = True  # precisa ter consultado o banco


def avaliar(caso: Caso, texto: str, consultas: list[str]) -> list[str]:
    """Devolve a lista de falhas (vazia = caso aprovado)."""
    falhas = []
    t = normalizar(texto)
    if caso.exige_sql and not consultas:
        falhas.append("não consultou o banco (resposta sem SQL)")
    for valor, tol_rel, tol_abs in caso.numeros:
        if not contem_numero(texto, valor, tol_rel, tol_abs):
            falhas.append(f"não citou o valor esperado {valor:g}")
    if caso.numeros_alguma and not any(contem_numero(texto, v, r, a) for v, r, a in caso.numeros_alguma):
        falhas.append("não citou nenhum dos valores aceitos: " + ", ".join(f"{v:g}" for v, _, _ in caso.numeros_alguma))
    for p in caso.todas:
        if normalizar(p) not in t:
            falhas.append(f"faltou mencionar '{p}'")
    if caso.alguma and not any(normalizar(p) in t for p in caso.alguma):
        falhas.append("não mencionou nenhum de: " + ", ".join(caso.alguma))
    for p in caso.proibidas:
        if p.lower() in texto.lower():  # literal: não normaliza (ex.: "°c" viraria "c")
            falhas.append(f"mencionou algo proibido: '{p}'")
    return falhas
