"""Pruebas de los consumidores: Subsidios migrado al gateway, app móvil de solo lectura y reglas del retiro."""

import json
import os
import time
import urllib.error
import urllib.request

import pytest

SUBSIDIOS = os.environ.get("SUBSIDIOS_URL", "http://subsidios-app:8091")
MOBILE = os.environ.get("MOBILE_APP_URL", "http://mobile-app:8094")


def http(method, url, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8") or "null")


def wait_for(url, seconds=30):
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            return http("GET", url)
        except OSError:
            time.sleep(1)
    pytest.fail("No respondió " + url)


def test_subsidios_registra_el_retiro_por_el_gateway(api, sample, legacy):
    _, state, _, _ = api.call("GET", "/api/v1/migration/status", "portal")
    if state["domains"]["affiliations"] == "LEGACY":
        pytest.skip("Afiliaciones está en LEGACY (rollback): Subsidios usa el camino legacy")
    wait_for(SUBSIDIOS + "/health")
    doc = sample["docs"]["subsidios"]
    body = {"documento": doc, "fecha": "2026-10-05", "motivo": "Retiro desde Subsidios"}
    first, created = http("POST", SUBSIDIOS + "/retiros", body)
    again, repeated = http("POST", SUBSIDIOS + "/retiros", body)
    assert first == 201 and created["movimiento"]
    assert again == 201 and repeated["movimiento"] == created["movimiento"]
    assert legacy.one("SELECT count(*) FROM logmov WHERE nro_doc = %s AND tip_mov = 'RET'", (doc,))[0] == 1
    with open(os.environ.get("AUDIT_LOG_PATH", "/logs/audit.log"), encoding="utf-8") as fh:
        entries = [json.loads(line) for line in fh.read().splitlines()[-300:] if line.strip()]
    masked = "*" * (len(doc) - 4) + doc[-4:]
    assert any(e["consumer"] == "subsidios" and masked in e["endpoint"] and e["status"] in (200, 201) for e in entries)


def test_request_id_de_otro_afiliado_responde_409(api, sample):
    body = {"requestId": "tests-409-" + sample["suffix"], "date": "2026-10-05", "reason": "Retiro de prueba"}
    status, _, _, _ = api.call("POST", "/api/v1/members/{0}/retirements".format(sample["docs"]["conflict"]), "portal", body)
    other, error, _, _ = api.call("POST", "/api/v1/members/{0}/retirements".format(sample["docs"]["active2"]), "portal", body)
    assert status in (200, 201)
    assert other == 409 and error["error_id"]


def test_metodo_no_permitido_responde_405(api, sample):
    status, body, _, _ = api.call("DELETE", "/api/v1/members/" + sample["docs"]["active"], "portal")
    assert status == 405 and body["error_id"]


def test_app_movil_consulta_y_no_puede_escribir(sample):
    wait_for(MOBILE + "/health")
    status, data = http("GET", MOBILE + "/api/members/" + sample["docs"]["active"])
    assert status == 200
    assert data["member"]["fullName"] == "ANA MARIA PRUEBA UNO" and len(data["beneficiaries"]) == 2
    write, error = http("POST", MOBILE + "/api/members/{0}/retirements".format(sample["docs"]["active"]))
    assert write == 403 and error["error_id"]
