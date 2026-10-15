"""panel-web — panel de demostración de Legacy Escape (puerto 8093).

Interfaz web para operar la capa de transición sin usar la terminal. Igual que el portal,
solo habla HTTP con el gateway (GATEWAY_URL) usando PORTAL_TOKEN: nunca toca la base legacy.
El token se queda en el servidor; el navegador solo ve /api/... de este panel.

GET  /                                   interfaz
GET  /api/status                         salud del gateway + estado de migración
GET  /api/members/{documento}            ficha: afiliado, beneficiarios y empresa
POST /api/members/{documento}/retirements  registra un retiro (requestId lo genera el navegador)
GET  /api/audit                          últimas líneas de logs/audit.log (ya enmascaradas)
"""

import json
import os
import re
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://gateway:8082").rstrip("/")
TOKEN = os.environ.get("PORTAL_TOKEN", "")
AUDIT_PATH = os.environ.get("AUDIT_LOG_PATH", "/logs/audit.log")
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


_migration = {"at": 0.0, "domains": {}}


def migration_domains(ttl=15):
    """Estado de migración con caché: el sondeo del panel no debe llenar la auditoría."""
    if time.time() - _migration["at"] > ttl or not _migration["domains"]:
        status, body = call("GET", "/api/v1/migration/status")
        if status == 200 and isinstance(body, dict):
            _migration.update(at=time.time(), domains=body.get("domains", {}))
    return _migration["domains"]


def audit_tail(limit=12):
    """Últimas peticiones de los consumidores (sin el sondeo de estado del propio panel)."""
    try:
        with open(AUDIT_PATH, encoding="utf-8", errors="replace") as fh:
            lines = [line for line in fh.read().splitlines()[-500:] if line.strip()]
    except OSError:
        return []
    entries = []
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("endpoint") != "/api/v1/migration/status":
            entries.append(entry)
        if len(entries) >= limit:
            break
    return entries


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
        if path == "/api/status":
            health_status, health = call("GET", "/health")
            return self._send(200, {
                "gateway": "UP" if health_status == 200 else "DOWN",
                "legacy": (health or {}).get("legacy", "DOWN") if health_status == 200 else "DOWN",
                "domains": migration_domains() if health_status == 200 else {},
            })
        if path == "/api/audit":
            return self._send(200, audit_tail())
        match = MEMBER.match(path)
        if match:
            doc = match.group(1)
            status, member = call("GET", "/api/v1/members/" + doc)
            if status != 200:
                return self._send(status, member)
            _, beneficiaries = call("GET", "/api/v1/members/{0}/beneficiaries".format(doc))
            company_id = (member.get("company") or {}).get("id")
            company = call("GET", "/api/v1/companies/{0}".format(company_id))[1] if company_id else None
            return self._send(200, {"member": member, "beneficiaries": beneficiaries if isinstance(beneficiaries, list) else [],
                                    "company": company})
        return self._send(404, {"message": "Ruta no encontrada"})

    def do_POST(self):
        match = RETIREMENT.match(self.path)
        if not match:
            return self._send(404, {"message": "Ruta no encontrada"})
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._send(400, {"message": "JSON inválido"})
        status, result = call("POST", "/api/v1/members/{0}/retirements".format(match.group(1)), {
            "requestId": str(body.get("requestId", ""))[:100], "date": body.get("date"), "reason": body.get("reason")})
        return self._send(status, result)

    def log_message(self, fmt, *args):
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8093), Handler).serve_forever()
