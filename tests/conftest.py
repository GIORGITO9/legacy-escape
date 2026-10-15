"""Fixtures de las pruebas del equipo.

Las pruebas corren contra el gateway en funcionamiento. Para no alterar los datos reales,
crean su propia empresa y afiliados de prueba directamente en la base (el servicio `tests`
puede hacerlo) y los borran al terminar.
"""

import json
import os
import random
import time
import urllib.error
import urllib.request

import psycopg2
import pytest

GATEWAY = os.environ.get("GATEWAY_URL", "http://gateway:8082").rstrip("/")


class Api:
    def __init__(self):
        self.tokens = {name: os.environ.get(name.upper() + "_TOKEN", "") for name in ("portal", "subsidios", "mobile")}

    def call(self, method, path, consumer=None, body=None, token=None, timeout=10):
        headers = {"Content-Type": "application/json"}
        token = token if token is not None else (self.tokens[consumer] if consumer else None)
        if token:
            headers["Authorization"] = "Bearer " + token
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(GATEWAY + path, data=data, headers=headers, method=method)
        started = time.time()
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                status, text = resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            status, text = exc.code, exc.read().decode("utf-8")
        try:
            payload = json.loads(text)
        except ValueError:
            payload = None
        return status, payload, text, time.time() - started


class Legacy:
    """Acceso directo a la base, solo para preparar y verificar las pruebas."""

    def __init__(self):
        self.conn = psycopg2.connect(
            host=os.environ.get("LEGACY_DB_HOST", "legacy-db"), port=int(os.environ.get("LEGACY_DB_PORT", "5432")),
            dbname=os.environ.get("POSTGRES_DB", "legacy"), user=os.environ.get("POSTGRES_USER", "legacy"),
            password=os.environ.get("POSTGRES_PASSWORD", ""), connect_timeout=5)
        self.conn.autocommit = True
        renamed = not self.one("SELECT to_regclass('public.afi_mae') IS NOT NULL")[0]
        if renamed:
            self.table, self.doc, self.status = "person_master", "document_number", "status_code"
        else:
            self.table, self.doc, self.status = "afi_mae", "nro_doc", "est_afi"

    def _sql(self, sql):
        return sql.format(t=getattr(self, "table", ""), d=getattr(self, "doc", ""), s=getattr(self, "status", ""))

    def one(self, sql, params=()):
        with self.conn.cursor() as cur:
            cur.execute(self._sql(sql), params)
            return cur.fetchone()

    def run(self, sql, params=()):
        with self.conn.cursor() as cur:
            cur.execute(self._sql(sql), params)


@pytest.fixture(scope="session")
def api():
    client = Api()
    deadline = time.time() + 90
    while time.time() < deadline:
        try:
            status, body, _, _ = client.call("GET", "/health")
            if status == 200 and body.get("legacy") == "UP":
                return client
        except Exception:  # noqa: BLE001 — el gateway todavía está arrancando
            pass
        time.sleep(1)
    pytest.fail("El gateway no respondió /health con legacy UP en 90 segundos")


@pytest.fixture(scope="session")
def legacy():
    db = Legacy()
    yield db
    db.conn.close()


@pytest.fixture(scope="session")
def sample(legacy, api):
    """Empresa de prueba con 5 afiliados activos (tres se retiran en las pruebas), 1 suspendido y 2 beneficiarios."""
    suffix = "".join(random.choice("0123456789") for _ in range(7))
    company = "T" + suffix[:6]
    docs = {"active": "98" + suffix + "1", "active2": "98" + suffix + "2",
            "suspended": "98" + suffix + "3", "retire": "98" + suffix + "4", "subsidios": "98" + suffix + "5",
            "conflict": "98" + suffix + "6"}
    bens = {"spouse": "97" + suffix + "1", "child": "97" + suffix + "2"}
    legacy.run("INSERT INTO empresa (cod_emp, nom_emp, nit, est_emp) VALUES (%s, %s, %s, 'A')",
               (company, "EMPRESA DE PRUEBAS SAS", "900000000"))
    members = [(docs["active"], "ANA", "MARIA", "PRUEBA", "UNO", "A"), (docs["active2"], "LUIS", None, "PRUEBA", None, "A"),
               (docs["suspended"], "JUAN", None, "PRUEBA", "TRES", "S"), (docs["retire"], "SOFIA", None, "PRUEBA", "CUATRO", "A"),
               (docs["subsidios"], "PABLO", None, "PRUEBA", "CINCO", "A"),
               (docs["conflict"], "LAURA", None, "PRUEBA", "SEIS", "A")]
    for doc, n1, n2, a1, a2, status in members:
        legacy.run("INSERT INTO {t} ({d}, tip_doc, nom1, nom2, ape1, ape2, {s}, cod_emp, fec_afi) "
                   "VALUES (%s, 'CC', %s, %s, %s, %s, %s, %s, DATE '2020-01-01')", (doc, n1, n2, a1, a2, status, company))
    legacy.run("INSERT INTO afi_ben (nro_doc_ben, nro_doc, nom1, nom2, ape1, ape2, cod_par) "
               "VALUES (%s, %s, 'PEDRO', NULL, 'PRUEBA', 'UNO', 'C')", (bens["spouse"], docs["active"]))
    legacy.run("INSERT INTO afi_ben (nro_doc_ben, nro_doc, nom1, nom2, ape1, ape2, cod_par) "
               "VALUES (%s, %s, 'LUCIA', 'ANA', 'PRUEBA', 'UNO', 'H')", (bens["child"], docs["active"]))
    yield {"company": company, "docs": docs, "bens": bens, "suffix": suffix}

    all_docs = list(docs.values())
    legacy.run("DELETE FROM afi_ben WHERE nro_doc = ANY(%s)", (all_docs,))
    legacy.run("DELETE FROM logmov WHERE nro_doc = ANY(%s)", (all_docs,))
    if legacy.one("SELECT to_regclass('public.gateway_retirement_requests') IS NOT NULL")[0]:
        legacy.run("DELETE FROM gateway_retirement_requests WHERE document = ANY(%s)", (all_docs,))
    legacy.run("DELETE FROM {t} WHERE {d} = ANY(%s)", (all_docs,))
    legacy.run("DELETE FROM empresa WHERE cod_emp = %s", (company,))
