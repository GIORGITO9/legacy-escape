"""subsidios-app — registra retiros de afiliados (SÍ se puede modificar).

Migrado: POST /retiros ahora registra el retiro por el gateway (POST /api/v1/members/{doc}/retirements)
con SUBSIDIOS_TOKEN. El camino legacy (sp_registrar_retiro) se conserva para el rollback:
- si el dominio affiliations está en LEGACY (./rollback.sh affiliations), o
- si el gateway está desactivado (no se puede conectar con él),
el retiro se registra directamente con el procedimiento, como antes.

POST /retiros  {"documento": "...", "fecha": "YYYY-MM-DD", "motivo": "...", "requestId": "opcional"}  (puerto 8091)
"""

import hashlib
import json
import os
import socket
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import psycopg2

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://gateway:8082").rstrip("/")
TOKEN = os.environ.get("SUBSIDIOS_TOKEN", "")


class GatewayUnreachable(Exception):
    """No se pudo conectar con el gateway: la petición nunca llegó."""


def connect():
    return psycopg2.connect(
        host=os.environ.get("LEGACY_DB_HOST", "legacy-db"),
        port=int(os.environ.get("LEGACY_DB_PORT", "5432")),
        dbname=os.environ.get("POSTGRES_DB", "legacy"),
        user=os.environ.get("POSTGRES_USER", "legacy"),
        password=os.environ.get("POSTGRES_PASSWORD", ""),
        connect_timeout=2,
    )


def registrar_retiro_legacy(documento, fecha, motivo):
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT sp_registrar_retiro(%s, %s, %s, %s)", (documento, fecha, motivo, "SUBSIDIOS"))
            movimiento = cur.fetchone()[0]
        conn.commit()
        return movimiento
    finally:
        conn.close()


def gateway(method, path, body=None, timeout=8):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(GATEWAY_URL + path, data=data, method=method, headers={
        "Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8") or "{}")
        except ValueError:
            return exc.code, {}
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (ConnectionRefusedError, socket.gaierror)):
            raise GatewayUnreachable(str(exc.reason)) from exc
        raise


def modo():
    """'gateway' si Afiliaciones está en DUAL/MODERN; 'legacy' si está en LEGACY o el gateway no existe."""
    try:
        status, body = gateway("GET", "/api/v1/migration/status", timeout=3)
    except (GatewayUnreachable, OSError):
        return "legacy"
    if status == 200 and (body.get("domains") or {}).get("affiliations") == "LEGACY":
        return "legacy"
    return "gateway"


def texto(raw):
    """Cuerpo como texto: UTF-8 y, si un cliente envía Latin-1 (curl en Windows), también se acepta."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def request_id_para(data):
    """Id de idempotencia: el que envía el cliente o uno derivado de los datos (un reintento no duplica)."""
    if data.get("requestId"):
        return str(data["requestId"])[:100]
    huella = hashlib.sha256("|".join([str(data["documento"]), str(data["fecha"]), str(data.get("motivo", "RETIRO"))]).encode("utf-8"))
    return "subsidios-" + huella.hexdigest()[:32]


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, {"status": "UP", "modo": modo()})
        return self._send(404, {"error": "ruta no encontrada"})

    def do_POST(self):
        if self.path != "/retiros":
            return self._send(404, {"error": "ruta no encontrada"})
        length = int(self.headers.get("Content-Length", "0"))
        try:
            data = json.loads(texto(self.rfile.read(length)) or "{}")
            documento, fecha = str(data["documento"]), str(data["fecha"])
        except (ValueError, KeyError, TypeError):
            return self._send(400, {"error": "se esperan documento y fecha"})
        motivo = data.get("motivo", "RETIRO")
        if modo() == "gateway":
            try:
                return self._por_gateway(documento, fecha, motivo, request_id_para(data))
            except GatewayUnreachable:
                pass  # el servicio nuevo está desactivado: camino legacy
            except OSError:
                return self._send(504, {"error": "el gateway no respondió a tiempo; reintente con el mismo requestId"})
        try:
            movimiento = registrar_retiro_legacy(documento, fecha, motivo)
        except psycopg2.Error as exc:
            return self._send(500, {"error": str(exc).strip()})
        return self._send(201, {"movimiento": movimiento})

    def _por_gateway(self, documento, fecha, motivo, request_id):
        status, body = gateway("POST", "/api/v1/members/{0}/retirements".format(documento),
                               {"requestId": request_id, "date": fecha, "reason": motivo})
        if status in (200, 201):
            return self._send(201, {"movimiento": body.get("movementId"), "requestId": request_id})
        if status == 202:
            return self._send(202, {"estado": "PENDIENTE", "requestId": request_id, "mensaje": body.get("message")})
        return self._send(status, {"error": body.get("message", "error del gateway"), "requestId": request_id})

    def log_message(self, fmt, *args):
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8091), Handler).serve_forever()
