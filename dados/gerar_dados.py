"""
Gera dados SINTÉTICOS de um restaurante de delivery fictício ("Sabor da Casa").

Cria dados/restaurante.db (SQLite) e avaliacao/avaliacoes_gabarito.csv.
Nenhum dado real é usado. A semente fixa torna o resultado reproduzível.

História plantada nos dados (para o agente descobrir):
  - Desde 01/10/2026 a unidade "Centro" passou a demorar mais para entregar
    (falta de entregadores): o tempo médio sobe, o volume de pedidos cai,
    os cancelamentos aumentam e as avaliações pioram, com muitas reclamações de atraso.
  - Em setembro houve uma promoção "Combo Família" que elevou o ticket nos fins de semana.
  - Aos sábados a feijoada vende bem mais.

Uso:  python dados/gerar_dados.py
"""

import csv
import random
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

SEMENTE = 27
INICIO = date(2026, 6, 1)
FIM = date(2026, 10, 31)
INCIDENTE_INICIO = date(2026, 10, 1)
PROMO_INICIO, PROMO_FIM = date(2026, 9, 1), date(2026, 9, 30)

RAIZ = Path(__file__).resolve().parent.parent
BANCO = RAIZ / "dados" / "restaurante.db"
GABARITO = RAIZ / "avaliacao" / "avaliacoes_gabarito.csv"

UNIDADES = {  # pedidos/dia de base (dia útil)
    "Centro": 42,
    "Pinheiros": 30,
    "Vila Nova": 24,
}

# (nome, categoria, preço, custo, popularidade)
CARDAPIO = [
    ("Feijoada Completa", "Pratos", 49.90, 19.0, 6),
    ("Parmegiana de Frango", "Pratos", 38.90, 14.0, 9),
    ("Strogonoff de Carne", "Pratos", 39.90, 15.5, 8),
    ("Filé à Parmegiana", "Pratos", 44.90, 18.0, 6),
    ("Salada Caesar", "Saladas", 29.90, 9.0, 4),
    ("Salada Tropical", "Saladas", 27.90, 8.5, 3),
    ("Hambúrguer da Casa", "Lanches", 32.90, 11.0, 9),
    ("Hambúrguer Duplo", "Lanches", 41.90, 15.0, 6),
    ("Batata Frita", "Acompanhamentos", 18.90, 5.0, 8),
    ("Onion Rings", "Acompanhamentos", 19.90, 5.5, 3),
    ("Refrigerante Lata", "Bebidas", 7.50, 2.5, 10),
    ("Suco Natural", "Bebidas", 12.90, 4.0, 5),
    ("Pudim", "Sobremesas", 14.90, 4.0, 4),
    ("Brownie", "Sobremesas", 16.90, 5.0, 3),
    ("Combo Família", "Combos", 119.90, 45.0, 0),  # só na promoção
]

PESO_DIA_SEMANA = [0.85, 0.85, 0.9, 1.0, 1.25, 1.45, 1.3]  # seg..dom
PESO_HORA = {11: 3, 12: 10, 13: 9, 14: 3, 18: 5, 19: 10, 20: 11, 21: 7, 22: 2}

COMENTARIOS = {
    "elogio": [
        "Comida chegou quentinha e muito saborosa!",
        "Melhor {item} da região, recomendo demais.",
        "Entrega rápida e embalagem caprichada.",
        "Porção generosa e preço justo, vou pedir de novo.",
        "Tudo perfeito, o {item} estava incrível.",
        "Atendimento excelente e comida no ponto.",
    ],
    "atraso": [
        "Demorou mais de uma hora para chegar, a comida veio fria.",
        "Atraso enorme na entrega, pedi às 19h e chegou depois das 20h30.",
        "O entregador demorou demais, o {item} chegou frio.",
        "Esperei quase duas horas pelo pedido. Inaceitável.",
        "Entrega muito lenta, perdi o horário do almoço.",
    ],
    "qualidade": [
        "O {item} veio sem tempero, decepcionante.",
        "Comida salgada demais, não consegui comer.",
        "O {item} estava ressecado e mal passado.",
        "Qualidade caiu bastante desde a última vez.",
    ],
    "pedido_errado": [
        "O pedido veio errado, faltou um item e veio outro no lugar.",
        "Pedi {item} e recebi outro prato, sem aviso.",
        "Veio faltando bebida e a sobremesa.",
    ],
    "preco": [
        "Achei caro pelo tamanho da porção.",
        "O preço do {item} está acima do que vale.",
        "Taxa de entrega muito alta para a distância.",
    ],
    "embalagem": [
        "A embalagem vazou na sacola, chegou tudo sujo.",
        "Marmita mal fechada, o molho do {item} derramou.",
        "Embalagem fraca, o {item} chegou amassado.",
    ],
}

NOTA_POR_CATEGORIA = {
    "elogio": ([4, 5], [0.3, 0.7]),
    "atraso": ([1, 2, 3], [0.5, 0.35, 0.15]),
    "qualidade": ([1, 2, 3], [0.35, 0.4, 0.25]),
    "pedido_errado": ([1, 2], [0.5, 0.5]),
    "preco": ([2, 3], [0.5, 0.5]),
    "embalagem": ([2, 3], [0.55, 0.45]),
}
# Distribuição de motivos quando NÃO há atraso grave
PESO_BASE = {"elogio": 74, "qualidade": 9, "pedido_errado": 6, "preco": 5, "embalagem": 6}

ESQUEMA = """
CREATE TABLE itens (
    id INTEGER PRIMARY KEY, nome TEXT NOT NULL, categoria TEXT NOT NULL,
    preco REAL NOT NULL, custo REAL NOT NULL
);
CREATE TABLE pedidos (
    id INTEGER PRIMARY KEY, data_hora TEXT NOT NULL, data TEXT NOT NULL,
    hora INTEGER NOT NULL, dia_semana TEXT NOT NULL, unidade TEXT NOT NULL,
    canal TEXT NOT NULL, status TEXT NOT NULL, valor_itens REAL NOT NULL,
    taxa_entrega REAL NOT NULL, valor_total REAL NOT NULL,
    tempo_entrega_min INTEGER
);
CREATE TABLE itens_pedido (
    pedido_id INTEGER NOT NULL REFERENCES pedidos(id),
    item_id INTEGER NOT NULL REFERENCES itens(id),
    quantidade INTEGER NOT NULL, preco_unitario REAL NOT NULL
);
CREATE TABLE avaliacoes (
    id INTEGER PRIMARY KEY, pedido_id INTEGER NOT NULL REFERENCES pedidos(id),
    data TEXT NOT NULL, unidade TEXT NOT NULL, nota INTEGER NOT NULL, comentario TEXT NOT NULL
);
CREATE INDEX idx_pedidos_data ON pedidos(data);
CREATE INDEX idx_pedidos_unidade ON pedidos(unidade);
"""

DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


def escolher_item(rng, dia, id_para_nome):
    pesos = []
    for i, (nome, _, _, _, pop) in enumerate(CARDAPIO):
        p = pop
        if nome == "Feijoada Completa" and dia.weekday() == 5:
            p *= 4
        if nome == "Combo Família":
            p = 5 if PROMO_INICIO <= dia <= PROMO_FIM and dia.weekday() >= 4 else 0
        pesos.append(p)
    return rng.choices(range(len(CARDAPIO)), weights=pesos)[0]


def tempo_entrega(rng, unidade, dia, hora):
    media = 34 if hora in (12, 13, 20, 21) else 29
    if unidade == "Centro" and dia >= INCIDENTE_INICIO:
        dias_desde = (dia - INCIDENTE_INICIO).days
        media += min(32, 12 + dias_desde * 0.8)  # piora gradual até +32 min
    return max(14, int(rng.gauss(media, 7)))


def escolher_categoria(rng, tempo):
    if tempo > 52 and rng.random() < 0.6:
        return "atraso"
    cats = list(PESO_BASE)
    return rng.choices(cats, weights=[PESO_BASE[c] for c in cats])[0]


def main():
    rng = random.Random(SEMENTE)
    BANCO.parent.mkdir(exist_ok=True)
    GABARITO.parent.mkdir(exist_ok=True)
    if BANCO.exists():
        BANCO.unlink()

    con = sqlite3.connect(BANCO)
    con.executescript(ESQUEMA)
    con.executemany(
        "INSERT INTO itens VALUES (?,?,?,?,?)",
        [(i + 1, n, c, p, k) for i, (n, c, p, k, _) in enumerate(CARDAPIO)],
    )

    pedido_id = 0
    aval_id = 0
    linhas_pedidos, linhas_itens, linhas_aval, gabarito = [], [], [], []

    dia = INICIO
    while dia <= FIM:
        for unidade, base in UNIDADES.items():
            volume = base * PESO_DIA_SEMANA[dia.weekday()]
            if unidade == "Centro" and dia >= INCIDENTE_INICIO:
                volume *= 0.72  # clientes desistem do Centro
            n = max(0, int(rng.gauss(volume, volume * 0.12)))
            horas = rng.choices(list(PESO_HORA), weights=list(PESO_HORA.values()), k=n)
            for hora in horas:
                pedido_id += 1
                momento = datetime(dia.year, dia.month, dia.day, hora, rng.randint(0, 59))
                canal = rng.choices(["app_proprio", "marketplace"], weights=[35, 65])[0]
                cancelamento = 0.08 if (unidade == "Centro" and dia >= INCIDENTE_INICIO) else 0.025
                status = "cancelado" if rng.random() < cancelamento else "entregue"

                itens_do_pedido = {}
                for _ in range(rng.choices([1, 2, 3], weights=[45, 40, 15])[0]):
                    idx = escolher_item(rng, dia, None)
                    itens_do_pedido[idx] = itens_do_pedido.get(idx, 0) + 1
                valor_itens = 0.0
                for idx, qtd in itens_do_pedido.items():
                    preco = CARDAPIO[idx][2]
                    valor_itens += preco * qtd
                    linhas_itens.append((pedido_id, idx + 1, qtd, preco))
                taxa = round(rng.choice([0, 4.9, 6.9, 8.9]), 2)
                tempo = tempo_entrega(rng, unidade, dia, hora) if status == "entregue" else None

                linhas_pedidos.append((
                    pedido_id, momento.isoformat(timespec="minutes"), dia.isoformat(), hora,
                    DIAS[dia.weekday()], unidade, canal, status, round(valor_itens, 2),
                    taxa, round(valor_itens + taxa, 2), tempo,
                ))

                if status == "entregue" and rng.random() < 0.30:
                    aval_id += 1
                    categoria = escolher_categoria(rng, tempo)
                    notas, pesos = NOTA_POR_CATEGORIA[categoria]
                    nota = rng.choices(notas, weights=pesos)[0]
                    nome_item = CARDAPIO[rng.choice(list(itens_do_pedido))][0]
                    texto = rng.choice(COMENTARIOS[categoria]).format(item=nome_item)
                    linhas_aval.append((aval_id, pedido_id, dia.isoformat(), unidade, nota, texto))
                    gabarito.append((aval_id, categoria, nota, texto))
        dia += timedelta(days=1)

    con.executemany("INSERT INTO pedidos VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", linhas_pedidos)
    con.executemany("INSERT INTO itens_pedido VALUES (?,?,?,?)", linhas_itens)
    con.executemany("INSERT INTO avaliacoes VALUES (?,?,?,?,?,?)", linhas_aval)
    con.commit()
    con.close()

    with GABARITO.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["avaliacao_id", "categoria_real", "nota", "comentario"])
        w.writerows(gabarito)

    print(f"Banco: {BANCO}")
    print(f"Pedidos: {len(linhas_pedidos)} | Itens: {len(linhas_itens)} | Avaliações: {len(linhas_aval)}")


if __name__ == "__main__":
    main()
