"""Adapter del sistema legacy (anticorrupción).

Es el ÚNICO lugar del código nuevo que conoce las tablas, columnas, códigos y
procedimientos heredados (AFI_MAE, AFI_BEN, EMPRESA, LOGMOV, sp_registrar_retiro).
Traduce todo al modelo canónico de app.domain.

Cambio de esquema del DBA (evento 1): AFI_MAE -> PERSON_MASTER, NRO_DOC ->
DOCUMENT_NUMBER, EST_AFI -> STATUS_CODE. El adapter conoce las dos variantes y
usa la que exista en la base, así que el contrato de la API no cambia.
"""

import os
import socket
import threading
import time

import psycopg2
import psycopg2.errors

from app.domain import (Beneficiary, Company, CompanyRef, LegacyUnavailable, Member, NotFound,
                        Retirement, full_name)

# Variantes conocidas del maestro de afiliados (antes y después del cambio de esquema).
MEMBER_SCHEMAS = [
    {"table": "afi_mae", "doc": "nro_doc", "status": "est_afi"},
    {"table": "person_master", "doc": "document_number", "status": "status_code"},
]

STATUS_CODES = {"A": "ACTIVE", "R": "RETIRED", "S": "SUSPENDED"}
RELATIONSHIP_CODES = {"C": "SPOUSE", "H": "CHILD", "P": "FATHER", "M": "MOTHER"}

# Tabla propia del gateway en la base legacy: garantiza que un requestId se aplique
# una sola vez (se inserta en la misma transacción que llama al procedimiento).
IDEMPOTENCY_DDL = """
CREATE TABLE IF NOT EXISTS gateway_retirement_requests (
    request_id      VARCHAR(100) PRIMARY KEY,
    document        VARCHAR(15)  NOT NULL,
    retirement_date DATE         NOT NULL,
    reason          VARCHAR(200),
    consumer        VARCHAR(20)  NOT NULL,
    movement_id     INTEGER,
    created_at      TIMESTAMP    NOT NULL DEFAULT now()
)
"""

SCHEMA_ERRORS = (psycopg2.errors.UndefinedTable, psycopg2.errors.UndefinedColumn)


class _TableMissing(Exception):
    pass


class LegacyMonitor:
    """Vigila la base en segundo plano (cada segundo) y guarda su IP.

    Con el contenedor detenido, el DNS de Docker tarda ~4 s en responder que el nombre no
    existe. Gracias al monitor las peticiones nunca esperan al DNS: si la base está caída
    fallan al instante (503 en milisegundos) y si está arriba se conectan directo a la IP.
    """

    def __init__(self, host, port, interval=1.0):
        self.host, self.port, self.interval = host, port, interval
        self.address = None   # última IP que respondió
        self.up = None        # None = todavía no se sabe
        threading.Thread(target=self._loop, name="legacy-monitor", daemon=True).start()

    def check(self):
        try:
            address = socket.getaddrinfo(self.host, self.port, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
            with socket.create_connection((address, self.port), timeout=1):
                pass
            self.address, self.up = address, True
        except OSError:
            self.up = False

    def mark_down(self):
        self.up = False

    def _loop(self):
        while True:
            self.check()
            time.sleep(self.interval)


class LegacyRepository:
    def __init__(self):
        self._schema_index = 0
        self._lock = threading.Lock()
        self._idempotency_ready = False
        self._host = os.environ.get("LEGACY_DB_HOST", "legacy-db")
        self._port = int(os.environ.get("LEGACY_DB_PORT", "5432"))
        self.monitor = LegacyMonitor(self._host, self._port)

    # ------------------------------------------------------------------ conexión

    def _connect(self):
        if self.monitor.up is False:
            raise LegacyUnavailable("legacy fuera de servicio (monitor)")
        address = {"hostaddr": self.monitor.address} if self.monitor.up and self.monitor.address else {}
        try:
            return psycopg2.connect(
                host=self._host,
                port=self._port,
                **address,
                dbname=os.environ.get("POSTGRES_DB", "legacy"),
                user=os.environ.get("POSTGRES_USER", "legacy"),
                password=os.environ.get("POSTGRES_PASSWORD", ""),
                connect_timeout=2,
                options="-c statement_timeout=2000",
                application_name="gateway-adapter",
            )
        except psycopg2.Error as exc:
            self.monitor.mark_down()
            raise LegacyUnavailable(str(exc)) from exc

    def _schemas(self):
        """Variantes del esquema, empezando por la última que funcionó."""
        start = self._schema_index
        return [(i, MEMBER_SCHEMAS[i]) for i in [start] + [j for j in range(len(MEMBER_SCHEMAS)) if j != start]]

    def _query_members(self, conn, sql_template, params, fetch="one"):
        """Ejecuta una consulta sobre el maestro de afiliados probando cada variante del esquema."""
        last_error = None
        for index, schema in self._schemas():
            try:
                with conn.cursor() as cur:
                    cur.execute(sql_template.format(**schema), params)
                    result = cur.fetchone() if fetch == "one" else cur.fetchall()
                self._schema_index = index
                return result
            except SCHEMA_ERRORS as exc:
                last_error = exc
                conn.rollback()
        raise RuntimeError("Esquema legacy no reconocido") from last_error

    def _read(self, fn):
        conn = self._connect()
        try:
            conn.autocommit = True
            return fn(conn)
        except psycopg2.OperationalError as exc:
            raise LegacyUnavailable(str(exc)) from exc
        finally:
            conn.close()

    # ------------------------------------------------------------------ lecturas

    def ping(self) -> bool:
        try:
            self._read(lambda conn: conn.cursor().execute("SELECT 1"))
            return True
        except LegacyUnavailable:
            return False

    def get_member(self, document: str) -> Member:
        sql = ("SELECT a.{doc}, a.nom1, a.nom2, a.ape1, a.ape2, a.{status}, a.cod_emp, e.nom_emp "
               "FROM {table} a LEFT JOIN empresa e ON e.cod_emp = a.cod_emp WHERE a.{doc} = %s")
        row = self._read(lambda conn: self._query_members(conn, sql, (document,)))
        if row is None:
            raise NotFound("Afiliado no encontrado")
        company = CompanyRef(id=row[6].strip(), name=(row[7] or "").strip()) if row[6] else None
        code = (row[5] or "").strip().upper()
        return Member(document=row[0].strip(), fullName=full_name(list(row[1:5])),
                      status=STATUS_CODES.get(code, "SUSPENDED"), company=company)

    def get_beneficiaries(self, document: str):
        def work(conn):
            exists = self._query_members(conn, "SELECT 1 FROM {table} WHERE {doc} = %s", (document,))
            if exists is None:
                raise NotFound("Afiliado no encontrado")
            with conn.cursor() as cur:
                cur.execute("SELECT nro_doc_ben, nom1, nom2, ape1, ape2, cod_par FROM afi_ben "
                            "WHERE nro_doc = %s ORDER BY nro_doc_ben", (document,))
                return cur.fetchall()

        rows = self._read(work)
        return [Beneficiary(document=r[0].strip(), fullName=full_name(list(r[1:5])),
                            relationship=RELATIONSHIP_CODES.get((r[5] or "").strip().upper(), "OTHER"))
                for r in rows]

    def get_company(self, company_id: str) -> Company:
        def work(conn):
            with conn.cursor() as cur:
                cur.execute("SELECT cod_emp, nom_emp FROM empresa WHERE cod_emp = %s", (company_id,))
                company = cur.fetchone()
            if company is None:
                raise NotFound("Empresa no encontrada")
            count = self._query_members(
                conn, "SELECT count(*) FROM {table} WHERE cod_emp = %s AND upper(trim({status})) = 'A'", (company_id,))
            return company, count[0]

        company, active = self._read(work)
        return Company(id=company[0].strip(), name=(company[1] or "").strip(), activeMembers=int(active))

    # ------------------------------------------------------------------ escritura

    def _ensure_idempotency_table(self, conn):
        if self._idempotency_ready:
            return
        with self._lock:
            with conn.cursor() as cur:
                cur.execute(IDEMPOTENCY_DDL)
            conn.commit()
            self._idempotency_ready = True

    def register_retirement(self, request_id, document, date, reason, consumer):
        """Registra el retiro con el procedimiento legacy, una sola vez por requestId.

        Devuelve (Retirement, creado). creado=False si el requestId ya se había aplicado.
        """
        try:
            return self._register_once(request_id, document, date, reason, consumer)
        except _TableMissing:
            return self._register_once(request_id, document, date, reason, consumer)

    def _register_once(self, request_id, document, date, reason, consumer):
        conn = self._connect()
        try:
            self._ensure_idempotency_table(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO gateway_retirement_requests (request_id, document, retirement_date, reason, consumer) "
                    "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (request_id) DO NOTHING RETURNING request_id",
                    (request_id, document, date, reason, consumer))
                inserted = cur.fetchone() is not None
                if not inserted:
                    cur.execute("SELECT document, retirement_date, reason, movement_id FROM gateway_retirement_requests "
                                "WHERE request_id = %s", (request_id,))
                    row = cur.fetchone()
                    conn.commit()
                    return Retirement(requestId=request_id, document=row[0], date=row[1].isoformat(),
                                      reason=row[2] or "", movementId=row[3]), False
                try:
                    cur.execute("SELECT sp_registrar_retiro(%s, %s, %s, %s)", (document, date, reason, consumer.upper()))
                except psycopg2.errors.RaiseException as exc:
                    conn.rollback()
                    if "AFI-404" in str(exc):
                        raise NotFound("Afiliado no encontrado") from exc
                    raise
                movement_id = cur.fetchone()[0]
                cur.execute("UPDATE gateway_retirement_requests SET movement_id = %s WHERE request_id = %s",
                            (movement_id, request_id))
            conn.commit()
            return Retirement(requestId=request_id, document=document, date=date, reason=reason,
                              movementId=movement_id), True
        except psycopg2.errors.UndefinedTable:
            # La tabla de idempotencia desapareció (por ejemplo, tras ./reset.sh): se vuelve a crear.
            conn.rollback()
            self._idempotency_ready = False
            raise _TableMissing()
        except psycopg2.OperationalError as exc:
            raise LegacyUnavailable(str(exc)) from exc
        finally:
            conn.close()
