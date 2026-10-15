"""Gateway API v1 — capa de transición del dominio Afiliaciones (puerto 8082).

Portal, Subsidios y la app móvil hablan solo con este servicio. El gateway usa el
modelo canónico (app.domain); el acceso a la base lo hace exclusivamente el adapter.
"""

import hmac
import json
import logging
import os
import re
import sys
import threading
import time
import uuid
from datetime import date as Date
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from adapter.legacy_repository import LegacyRepository
from app.domain import LegacyUnavailable, NotFound
from app.service import RetirementService
from app.store import Store

logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("gateway")

AUDIT_PATH = os.environ.get("AUDIT_LOG_PATH", "/app/logs/audit.log")
WRITERS = {"portal", "subsidios"}

ROUTES = [
    ("GET", re.compile(r"^/health$"), "health"),
    ("GET", re.compile(r"^/api/v1/members/([^/]+)$"), "member"),
    ("GET", re.compile(r"^/api/v1/members/([^/]+)/beneficiaries$"), "beneficiaries"),
    ("GET", re.compile(r"^/api/v1/companies/([^/]+)$"), "company"),
    ("POST", re.compile(r"^/api/v1/members/([^/]+)/retirements$"), "retirement"),
    ("GET", re.compile(r"^/api/v1/migration/status$"), "migration_status"),
]
DOCUMENT = re.compile(r"^[0-9]{3,15}$")
COMPANY_ID = re.compile(r"^[A-Za-z0-9-]{1,10}$")


def mask(text):
    """Deja visibles como máximo los últimos 4 dígitos de cualquier número de 5 o más dígitos."""
    return re.sub(r"\d{5,}", lambda m: "*" * (len(m.group(0)) - 4) + m.group(0)[-4:], text or "")


class ApiError(Exception):
    def __init__(self, status, message, code=None):
        super().__init__(message)
        self.status, self.message, self.code = status, message, code


class Audit:
    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)

    def write(self, consumer, method, path, status, latency_ms):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "consumer": consumer,
            "method": method,
            "endpoint": mask(path),
            "status": status,
            "latency_ms": latency_ms,
        }
        line = json.dumps(entry, ensure_ascii=False)
        with self._lock:
            try:
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except OSError:
                log.exception("no se pudo escribir la auditoría")


def load_tokens():
    tokens = {}
    for variable, consumer in (("PORTAL_TOKEN", "portal"), ("SUBSIDIOS_TOKEN", "subsidios"), ("MOBILE_TOKEN", "mobile")):
        value = os.environ.get(variable, "").strip()
        if value:
            tokens[value] = consumer
    return tokens


class Gateway:
    def __init__(self):
        self.repository = LegacyRepository()
        self.store = Store()
        self.retirements = RetirementService(self.repository, self.store)
        self.audit = Audit(AUDIT_PATH)
        self.tokens = load_tokens()

    def consumer_for(self, header):
        if not header or not header.lower().startswith("bearer "):
            return None
        presented = header[7:].strip()
        for token, consumer in self.tokens.items():
            if hmac.compare_digest(presented.encode("utf-8"), token.encode("utf-8")):
                return consumer
        return None

    # ------------------------------------------------------------------ handlers

    def health(self, consumer, args, body):
        return 200, {"status": "UP", "legacy": "UP" if self.repository.ping() else "DOWN"}

    def member(self, consumer, args, body):
        return 200, self.repository.get_member(self._document(args[0])).to_dict()

    def beneficiaries(self, consumer, args, body):
        return 200, [b.to_dict() for b in self.repository.get_beneficiaries(self._document(args[0]))]

    def company(self, consumer, args, body):
        if not COMPANY_ID.match(args[0]):
            raise NotFound("Empresa no encontrada")
        return 200, self.repository.get_company(args[0]).to_dict()

    def migration_status(self, consumer, args, body):
        return 200, {"domains": self.store.domain_states()}

    def retirement(self, consumer, args, body):
        if consumer not in WRITERS:
            raise ApiError(403, "El consumidor no tiene permiso de escritura")
        document = self._document(args[0])
        data = self._json(body)
        request_id = str(data.get("requestId") or "").strip()
        if not request_id or len(request_id) > 100:
            raise ApiError(400, "requestId es obligatorio (máximo 100 caracteres)")
        try:
            retirement_date = Date.fromisoformat(str(data.get("date", ""))).isoformat()
        except ValueError:
            raise ApiError(400, "date debe tener el formato AAAA-MM-DD")
        reason = str(data.get("reason") or "RETIRO").strip()[:200] or "RETIRO"
        return self.retirements.register(request_id, document, retirement_date, reason, consumer)

    @staticmethod
    def _document(value):
        if not DOCUMENT.match(value):
            raise NotFound("Afiliado no encontrado")
        return value

    @staticmethod
    def _json(body):
        try:
            data = json.loads(body.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            raise ApiError(400, "El cuerpo debe ser JSON válido")
        if not isinstance(data, dict):
            raise ApiError(400, "El cuerpo debe ser un objeto JSON")
        return data

    # ------------------------------------------------------------------ despacho

    def dispatch(self, method, raw_path, headers, body):
        path = urlsplit(raw_path).path.rstrip("/") or "/"
        consumer = self.consumer_for(headers.get("Authorization"))
        route, args, allowed = None, (), False
        for route_method, pattern, name in ROUTES:
            match = pattern.match(path)
            if match:
                allowed = True
                if route_method == method:
                    route, args = name, match.groups()
                    break
        try:
            if route is None:
                raise ApiError(405 if allowed else 404, "Método no permitido" if allowed else "Ruta no encontrada")
            if route != "health" and consumer is None:
                raise ApiError(401, "Token ausente o inválido")
            status, payload = getattr(self, route)(consumer, args, body)
        except ApiError as exc:
            status, payload = exc.status, self._error(exc.message, exc.code)
        except NotFound as exc:
            status, payload = 404, self._error(str(exc))
        except LegacyUnavailable:
            status, payload = 503, self._error("El sistema legacy no está disponible; intente más tarde", "LEGACY_UNAVAILABLE")
        except Exception as exc:  # noqa: BLE001 — nunca se exponen trazas ni SQL al cliente
            error = self._error("Error interno")
            log.error("error_id=%s %s %s: %r", error["error_id"], method, mask(path), exc)
            status, payload = 500, error
        return consumer or "anonymous", path, status, payload

    @staticmethod
    def _error(message, code=None):
        payload = {"message": message, "error_id": str(uuid.uuid4())}
        if code:
            payload["code"] = code
        return payload


GATEWAY = None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _handle(self, method):
        started = time.monotonic()
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length > 0 else b""
        consumer, path, status, payload = GATEWAY.dispatch(method, self.path, self.headers, body)
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        GATEWAY.audit.write(consumer, method, path, status, int(round((time.monotonic() - started) * 1000)))
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")

    def log_message(self, fmt, *args):
        return


def main():
    global GATEWAY
    GATEWAY = Gateway()
    GATEWAY.retirements.start_worker()
    port = int(os.environ.get("GATEWAY_PORT", "8082"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    server.daemon_threads = True
    log.info("gateway escuchando en :%s", port)
    server.serve_forever()


if __name__ == "__main__":
    main()
