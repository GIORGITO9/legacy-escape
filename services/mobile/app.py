"""mobile-app — app móvil de afiliados (evento 3: nuevo consumidor), puerto 8094.

Consulta afiliados y beneficiarios usando la API existente del gateway con MOBILE_TOKEN:
sin acceso a la base y sin permisos de escritura (el gateway responde 403 si intenta escribir).
El token se queda en el servidor; el teléfono solo habla con /api/... de esta app.

GET  /                                      interfaz móvil
GET  /api/members/{documento}               afiliado + beneficiarios
POST /api/members/{documento}/retirements   se reenvía al gateway para demostrar el 403
"""

import json
import os
import re
import urllib.error
import urllib.request
import uuid
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://gateway:8082").rstrip("/")
TOKEN = os.environ.get("MOBILE_TOKEN", "")
HERE = os.path.dirname(os.path.abspath(__file__))
MEMBER = re.compile(r"^/api/members/([0-9]{1,15})$")
RETIREMENT = re.compile(r"^/api/members/([0-9]{1,15})/retirements$")


def call(method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(GATEWAY_URL + path, data=data, method=method, headers={
        "Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=6) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8") or "null")
        except ValueError:
            return exc.code, {"message": "Respuesta inválida del gateway"}
    except Exception:  # noqa: BLE001 — gateway apagado o inalcanzable
        return 502, {"message": "Gateway no disponible"}


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, payload, content_type="application/json; charset=utf-8"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), "rb") as fh:
                return self._send(200, fh.read(), "text/html; charset=utf-8")
        if path == "/health":
            return self._send(200, {"status": "UP"})
        match = MEMBER.match(path)
        if match:
            doc = match.group(1)
            status, member = call("GET", "/api/v1/members/" + doc)
            if status != 200:
                return self._send(status, member)
            _, beneficiaries = call("GET", "/api/v1/members/{0}/beneficiaries".format(doc))
            return self._send(200, {"member": member, "beneficiaries": beneficiaries if isinstance(beneficiaries, list) else []})
        return self._send(404, {"message": "Ruta no encontrada"})

    def do_POST(self):
        match = RETIREMENT.match(self.path)
        if not match:
            return self._send(404, {"message": "Ruta no encontrada"})
        status, body = call("POST", "/api/v1/members/{0}/retirements".format(match.group(1)), {
            "requestId": "mobile-" + uuid.uuid4().hex, "date": date.today().isoformat(), "reason": "Intento desde la app móvil"})
        return self._send(status, body)

    def log_message(self, fmt, *args):
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8094), Handler).serve_forever()
