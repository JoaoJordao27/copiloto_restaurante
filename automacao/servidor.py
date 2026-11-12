"""
Servidor local mínimo (só biblioteca padrão) para o n8n buscar o relatório diário por HTTP.

  python automacao/servidor.py                     # http://127.0.0.1:8765
  python automacao/servidor.py --host 0.0.0.0      # necessário se o n8n roda no Docker (use um token!)

Rotas:
  GET /saude                                  -> {"ok": true}
  GET /relatorio?data=AAAA-MM-DD&ia=1         -> JSON com texto, html, assunto, alertas...
     data: opcional (padrão = último dia com dados); ia: 1 para incluir resumo do Gemini

Segurança: se a variável RELATORIO_TOKEN existir, toda chamada precisa do cabeçalho X-Token igual a ela.
"""

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from automacao.relatorio_diario import gerar  # noqa: E402


class Handler(BaseHTTPRequestHandler):
    def _responder(self, codigo: int, corpo: dict):
        dados = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def do_GET(self):  # noqa: N802
        token = os.getenv("RELATORIO_TOKEN")
        if token and self.headers.get("X-Token") != token:
            return self._responder(401, {"erro": "token inválido"})
        url = urlparse(self.path)
        if url.path == "/saude":
            return self._responder(200, {"ok": True})
        if url.path != "/relatorio":
            return self._responder(404, {"erro": "rota não encontrada"})
        q = parse_qs(url.query)
        try:
            dados = gerar(q.get("data", [None])[0], ia=q.get("ia", ["0"])[0] in ("1", "true", "sim"))
        except ValueError as e:
            return self._responder(400, {"erro": str(e)})
        except Exception as e:  # noqa: BLE001
            return self._responder(500, {"erro": f"falha ao gerar o relatório: {str(e)[:200]}"})
        return self._responder(200, dados)

    def log_message(self, formato, *args):  # log curto, sem IP
        print("[servidor] " + formato % args)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--porta", type=int, default=8765)
    a = ap.parse_args()
    if a.host != "127.0.0.1" and not os.getenv("RELATORIO_TOKEN"):
        print("[aviso] escutando fora do localhost sem RELATORIO_TOKEN: defina um token para proteger o relatório.")
    print(f"Servidor em http://{a.host}:{a.porta}  (Ctrl+C para parar)")
    ThreadingHTTPServer((a.host, a.porta), Handler).serve_forever()


if __name__ == "__main__":
    main()
