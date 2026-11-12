"""Testes dos verificadores (rodar com: python -m pytest avaliacao -q)."""

from avaliacao.verificadores import Caso, avaliar, contem_numero, numeros


def test_numeros_formato_brasileiro():
    assert numeros("Faturamento de R$ 152.184,00 em outubro") == [152184.0]
    assert numeros("foram 2.691 pedidos.") == [2691.0]
    assert numeros("taxa de 4,6%") == [4.6]
    assert numeros("cerca de R$ 152,2 mil") == [152200.0]
    assert numeros("ticket de 56.55") == [56.55]


def test_contem_numero_com_tolerancia():
    assert contem_numero("R$ 152,2 mil", 152184, tol_rel=0.005)
    assert not contem_numero("R$ 150 mil", 152184, tol_rel=0.005)
    assert contem_numero("nota 3,97", 3.9673, tol_abs=0.011)


def test_avaliar_aprova_e_reprova():
    c = Caso("x", "n", "?", numeros=[(2691, 0, 0.5)], todas=["Centro"])
    assert avaliar(c, "O Centro entregou 2.691 pedidos", ["SELECT 1"]) == []
    falhas = avaliar(c, "Foram 100 pedidos", [])
    assert len(falhas) == 3  # sem SQL, sem o número, sem 'Centro'


def test_palavras_ignoram_acento_e_caixa():
    c = Caso("x", "n", "?", alguma=["não posso"], exige_sql=False)
    assert avaliar(c, "NAO POSSO fazer isso", []) == []


def test_proibidas():
    c = Caso("x", "n", "?", proibidas=["consultar_sql"], exige_sql=False)
    assert avaliar(c, "use a ferramenta consultar_sql", [])


def test_proibidas_nao_confunde_simbolo_com_letra():
    c = Caso("x", "n", "?", proibidas=["°c"], exige_sql=False)
    assert avaliar(c, "Não tenho dados sobre o clima.", []) == []
    assert avaliar(c, "Vai fazer 25°C amanhã.", [])
