"""Casos de uso del gateway: retiros idempotentes y tolerantes a la caída del legacy."""

import logging
import threading
import time

from app.domain import Conflict, LegacyUnavailable, NotFound, Retirement
from app.store import APPLIED, PENDING, REJECTED

log = logging.getLogger("gateway.service")


class RetirementService:
    def __init__(self, repository, store, retry_seconds=2.0):
        self.repository = repository
        self.store = store
        self.retry_seconds = retry_seconds

    def register(self, request_id, document, date, reason, consumer):
        """Devuelve (status HTTP, cuerpo).

        201 aplicado ahora · 200 requestId repetido · 202 aceptado con el legacy caído
        (se aplica al recuperarse, una sola vez) · NotFound si el afiliado no existe.
        """
        local = self.store.get_retirement(request_id)
        if local and local["document"] != document:
            raise Conflict("El requestId ya se usó para otro afiliado")
        if local and local["status"] == APPLIED:
            return 200, local["result"]
        if local and local["status"] == REJECTED:
            raise NotFound("Afiliado no encontrado")
        if local:  # pendiente: se usan los datos de la primera solicitud
            document, date, reason, consumer = local["document"], local["date"], local["reason"], local["consumer"]
        try:
            retirement, created = self.repository.register_retirement(request_id, document, date, reason, consumer)
        except Conflict:
            raise
        except NotFound:
            if local:
                self.store.save_result(request_id, document, date, reason, consumer, REJECTED, None)
            raise
        except LegacyUnavailable:
            self.store.save_pending(request_id, document, date, reason, consumer)
            pending = Retirement(requestId=request_id, document=document, date=date, reason=reason, state=PENDING)
            pending.extra["message"] = "Legacy no disponible: el retiro quedó en cola y se aplicará una sola vez al recuperarse"
            return 202, pending.to_dict()
        body = retirement.to_dict()
        self.store.save_result(request_id, retirement.document, retirement.date, retirement.reason, consumer, APPLIED, body)
        return (201 if created and not local else 200), body

    def drain_once(self):
        """Aplica los retiros pendientes. Se detiene en cuanto el legacy sigue caído."""
        for item in self.store.pending():
            try:
                retirement, _ = self.repository.register_retirement(
                    item["request_id"], item["document"], item["date"], item["reason"], item["consumer"])
                self.store.save_result(item["request_id"], item["document"], item["date"], item["reason"],
                                       item["consumer"], APPLIED, retirement.to_dict())
                log.info("retiro pendiente aplicado: %s", item["request_id"])
            except (NotFound, Conflict):
                self.store.save_result(item["request_id"], item["document"], item["date"], item["reason"],
                                       item["consumer"], REJECTED, None)
            except LegacyUnavailable:
                return
            except Exception:  # noqa: BLE001 — el worker no debe morir
                log.exception("error aplicando retiro pendiente %s", item["request_id"])

    def start_worker(self):
        def loop():
            while True:
                try:
                    if self.store.count_pending():
                        self.drain_once()
                except Exception:  # noqa: BLE001
                    log.exception("error en el worker de retiros")
                time.sleep(self.retry_seconds)

        thread = threading.Thread(target=loop, name="retirement-outbox", daemon=True)
        thread.start()
        return thread
