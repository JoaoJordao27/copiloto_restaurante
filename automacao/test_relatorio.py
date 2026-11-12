"""Testes do relatório diário (rodar com: python -m pytest automacao -q). Usam o banco real, sem IA."""

import json
import os
import sqlite3
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from automacao import relatorio_diario as rd
from automacao.servidor import Handler


def _sql(sql: str):
    con = sqlite3.connect(f"file:{rd.BANCO}?mode=ro", uri=True)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def test_numeros_do_dia_batem_com_o_banco():
    d = rd.gerar("2026-10-31")
    fat, n = _sql("SELECT SUM(valor_total), COUNT(*) FROM pedidos "
                  "WHERE data = '2026-10-31' AND status != 'cancelado'")[0]
    assert d["geral"]["faturamento"] == pytest.approx(fat)
    assert d["geral"]["pedidos"] == n
    assert sum(u["faturamento"] for u in d["unidades"]) == pytest.approx(fat)


def test_media_do_mesmo_dia_da_semana():
    # sábados anteriores a 31/10/2026: 03, 10, 17 e 24/10
    datas = "','".join(["2026-10-03", "2026-10-10", "2026-10-17", "2026-10-24"])
    total = _sql(f"SELECT SUM(valor_total) FROM pedidos WHERE data IN ('{datas}') AND status != 'cancelado'")[0][0]
    d = rd.gerar("2026-10-31")
    assert d["geral"]["faturamento_habitual"] == pytest.approx(total / 4)


def test_alerta_do_centro_em_31_de_outubro():
    d = rd.gerar("2026-10-31")
    textos = " ".join(d["alertas"])
    assert "Centro" in textos and "tempo médio" in textos
    assert d["assunto"].startswith("Sabor da Casa") and "alerta" in d["assunto"]


def test_regras_de_alerta_isoladas():
    ind = {"pedidos": 10, "tempo_medio_min": 50, "cancelamento_pct": 2, "faturamento": 700,
           "nota_media": 4.5, "avaliacoes": 10}
    a = rd.alertas_da_unidade("X", ind, fat_base=1000)  # tempo alto + queda de 30%
    assert len(a) == 2
    ok = dict(ind, tempo_medio_min=30, faturamento=1000)
    assert rd.alertas_da_unidade("X", ok, fat_base=1000) == []


def test_data_sem_pedidos_levanta_erro():
    with pytest.raises(ValueError):
        rd.gerar("2020-01-01")


def test_html_escapa_comentarios():
    d = rd.gerar("2026-10-31")
    assert "<script" not in d["html"] and "Sabor da Casa" in d["html"]


@pytest.fixture
def servidor():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_servidor_responde_json(servidor):
    codigo, corpo = _get(servidor + "/relatorio?data=2026-10-31")
    assert codigo == 200 and corpo["data"] == "2026-10-31" and corpo["alertas"]
    assert _get(servidor + "/saude") == (200, {"ok": True})
    assert _get(servidor + "/relatorio?data=2020-01-01")[0] == 400
    assert _get(servidor + "/nada")[0] == 404


def test_servidor_exige_token_quando_configurado(servidor, monkeypatch):
    monkeypatch.setenv("RELATORIO_TOKEN", "segredo")
    assert _get(servidor + "/saude")[0] == 401
    assert _get(servidor + "/saude", {"X-Token": "segredo"})[0] == 200
    monkeypatch.delenv("RELATORIO_TOKEN")
    assert "RELATORIO_TOKEN" not in os.environ
