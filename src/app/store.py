"""Almacén local del gateway (SQLite en un volumen propio, independiente de la base legacy).

Guarda dos cosas que deben sobrevivir a una caída del legacy:
- el estado de migración de cada dominio (LEGACY / DUAL / MODERN), que cambia ./rollback.sh;
- la bandeja de salida de retiros aceptados con 202 mientras el legacy estaba caído.
"""

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone

from app.domain import DOMAINS, MIGRATION_STATES

DEFAULT_STATES = {"affiliations": "DUAL", "companies": "LEGACY", "contributions": "LEGACY"}

PENDING, APPLIED, REJECTED = "PENDING", "APPLIED", "REJECTED"


def _now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path=None):
        self.path = path or os.environ.get("STATE_DB_PATH", "/data/gateway.db")
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("CREATE TABLE IF NOT EXISTS domain_state (domain TEXT PRIMARY KEY, state TEXT NOT NULL, updated_at TEXT NOT NULL)")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS retirement_outbox (request_id TEXT PRIMARY KEY, document TEXT NOT NULL, "
            "date TEXT NOT NULL, reason TEXT, consumer TEXT NOT NULL, status TEXT NOT NULL, result TEXT, "
            "attempts INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
        for domain, state in DEFAULT_STATES.items():
            self._conn.execute("INSERT OR IGNORE INTO domain_state VALUES (?, ?, ?)", (domain, state, _now()))

    # ------------------------------------------------------------------ estado de migración

    def domain_states(self):
        with self._lock:
            rows = self._conn.execute("SELECT domain, state FROM domain_state").fetchall()
        return {domain: state for domain, state in rows}

    def set_domain_state(self, domain, state):
        if domain not in DOMAINS:
            raise ValueError("Dominio desconocido: {0} (válidos: {1})".format(domain, ", ".join(DOMAINS)))
        if state not in MIGRATION_STATES:
            raise ValueError("Estado inválido: {0} (válidos: {1})".format(state, ", ".join(MIGRATION_STATES)))
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO domain_state VALUES (?, ?, ?)", (domain, state, _now()))

    # ------------------------------------------------------------------ bandeja de retiros

    def get_retirement(self, request_id):
        with self._lock:
            row = self._conn.execute(
                "SELECT request_id, document, date, reason, consumer, status, result FROM retirement_outbox WHERE request_id = ?",
                (request_id,)).fetchone()
        if row is None:
            return None
        keys = ["request_id", "document", "date", "reason", "consumer", "status", "result"]
        item = dict(zip(keys, row))
        item["result"] = json.loads(item["result"]) if item["result"] else None
        return item

    def save_pending(self, request_id, document, date, reason, consumer):
        """Guarda el retiro pendiente. Devuelve False si el requestId ya existía."""
        with self._lock:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO retirement_outbox (request_id, document, date, reason, consumer, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (request_id, document, date, reason, consumer, PENDING, _now(), _now()))
            return cur.rowcount == 1

    def save_result(self, request_id, document, date, reason, consumer, status, result):
        with self._lock:
            self._conn.execute(
                "INSERT INTO retirement_outbox (request_id, document, date, reason, consumer, status, result, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(request_id) DO UPDATE SET status = excluded.status, "
                "result = excluded.result, updated_at = excluded.updated_at",
                (request_id, document, date, reason, consumer, status, json.dumps(result), _now(), _now()))

    def pending(self, limit=50):
        with self._lock:
            rows = self._conn.execute(
                "SELECT request_id, document, date, reason, consumer FROM retirement_outbox WHERE status = ? "
                "ORDER BY created_at LIMIT ?", (PENDING, limit)).fetchall()
            self._conn.executemany("UPDATE retirement_outbox SET attempts = attempts + 1 WHERE request_id = ?",
                                   [(r[0],) for r in rows])
        return [dict(zip(["request_id", "document", "date", "reason", "consumer"], r)) for r in rows]

    def count_pending(self):
        with self._lock:
            return self._conn.execute("SELECT count(*) FROM retirement_outbox WHERE status = ?", (PENDING,)).fetchone()[0]
