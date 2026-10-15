"""Pruebas de contrato del gateway (Legacy Escape) contra la API en funcionamiento."""

import json
import os
import re

LEGACY_KEYS = {"NRO_DOC", "NOM1", "NOM2", "APE1", "APE2", "EST_AFI", "COD_EMP", "NOM_EMP", "COD_PAR",
               "NRO_DOC_BEN", "DOCUMENT_NUMBER", "STATUS_CODE"}
AUDIT_FIELDS = ["timestamp", "consumer", "endpoint", "status", "latency_ms"]


def keys_of(obj):
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield key
            yield from keys_of(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from keys_of(item)


def test_health_reporta_legacy_up(api):
    status, body, _, _ = api.call("GET", "/health")
    assert status == 200
    assert body == {"status": "UP", "legacy": "UP"}


def test_sin_token_responde_401(api, sample):
    status, body, _, _ = api.call("GET", "/api/v1/members/" + sample["docs"]["active"])
    assert status == 401
    assert body["message"] and body["error_id"]


def test_token_invalido_responde_401(api, sample):
    status, _, _, _ = api.call("GET", "/api/v1/members/" + sample["docs"]["active"], token="token-que-no-existe")
    assert status == 401


def test_afiliado_en_modelo_canonico(api, sample):
    status, body, _, _ = api.call("GET", "/api/v1/members/" + sample["docs"]["active"], "portal")
    assert status == 200
    assert body == {"document": sample["docs"]["active"], "fullName": "ANA MARIA PRUEBA UNO", "status": "ACTIVE",
                    "company": {"id": sample["company"], "name": "EMPRESA DE PRUEBAS SAS"}}


def test_afiliado_suspendido_sin_columnas_legacy(api, sample):
    status, body, _, _ = api.call("GET", "/api/v1/members/" + sample["docs"]["suspended"], "portal")
    assert status == 200 and body["status"] == "SUSPENDED"
    assert not [k for k in keys_of(body) if k.upper() in LEGACY_KEYS]


def test_afiliado_inexistente_404_sin_trazas(api):
    status, body, text, _ = api.call("GET", "/api/v1/members/0000000001", "portal")
    assert status == 404
    assert body["message"] and body["error_id"]
    assert not re.search(r"Traceback|Exception|SELECT|afi_mae|nro_doc|psycopg", text)


def test_ruta_desconocida_404_con_formato(api):
    status, body, _, _ = api.call("GET", "/api/v1/no-existe", "portal")
    assert status == 404 and body["message"] and body["error_id"]


def test_beneficiarios_con_parentesco_canonico(api, sample):
    status, body, _, _ = api.call("GET", "/api/v1/members/{0}/beneficiaries".format(sample["docs"]["active"]), "portal")
    assert status == 200
    assert sorted(body, key=lambda b: b["document"]) == [
        {"document": sample["bens"]["spouse"], "fullName": "PEDRO PRUEBA UNO", "relationship": "SPOUSE"},
        {"document": sample["bens"]["child"], "fullName": "LUCIA ANA PRUEBA UNO", "relationship": "CHILD"},
    ]


def test_beneficiarios_lista_vacia(api, sample):
    status, body, _, _ = api.call("GET", "/api/v1/members/{0}/beneficiaries".format(sample["docs"]["active2"]), "mobile")
    assert status == 200 and body == []


def test_beneficiarios_de_inexistente_404(api):
    status, _, _, _ = api.call("GET", "/api/v1/members/0000000001/beneficiaries", "portal")
    assert status == 404


def test_empresa_cuenta_afiliados_activos(api, sample, legacy):
    status, body, _, _ = api.call("GET", "/api/v1/companies/" + sample["company"], "portal")
    expected = legacy.one("SELECT count(*) FROM {t} WHERE cod_emp = %s AND {s} = 'A'", (sample["company"],))[0]
    assert status == 200
    assert body == {"id": sample["company"], "name": "EMPRESA DE PRUEBAS SAS", "activeMembers": expected}


def test_empresa_inexistente_404(api):
    status, body, _, _ = api.call("GET", "/api/v1/companies/NOEXISTE", "portal")
    assert status == 404 and body["error_id"]


def test_mobile_lee_pero_no_escribe(api, sample):
    read, _, _, _ = api.call("GET", "/api/v1/members/" + sample["docs"]["active"], "mobile")
    write, body, _, _ = api.call("POST", "/api/v1/members/{0}/retirements".format(sample["docs"]["active"]), "mobile",
                                 {"requestId": "tests-mobile-" + sample["suffix"], "date": "2026-10-05", "reason": "prueba"})
    assert read == 200
    assert write == 403 and body["error_id"]


def test_retiro_valida_el_cuerpo(api, sample):
    status, _, _, _ = api.call("POST", "/api/v1/members/{0}/retirements".format(sample["docs"]["retire"]), "portal",
                               {"date": "no-es-fecha", "reason": "prueba"})
    assert status == 400


def test_retiro_de_inexistente_404(api, sample):
    status, _, _, _ = api.call("POST", "/api/v1/members/0000000001/retirements", "subsidios",
                               {"requestId": "tests-404-" + sample["suffix"], "date": "2026-10-05", "reason": "prueba"})
    assert status == 404


def test_retiro_queda_en_legacy_y_es_idempotente(api, sample, legacy):
    doc = sample["docs"]["retire"]
    body = {"requestId": "tests-retiro-" + sample["suffix"], "date": "2026-10-05", "reason": "Retiro de prueba"}
    first, created, _, _ = api.call("POST", "/api/v1/members/{0}/retirements".format(doc), "subsidios", body)
    second, repeated, _, _ = api.call("POST", "/api/v1/members/{0}/retirements".format(doc), "subsidios", body)
    assert first == 201 and second == 200
    assert created["movementId"] == repeated["movementId"]
    assert legacy.one("SELECT {s} FROM {t} WHERE {d} = %s", (doc,))[0] == "R"
    assert legacy.one("SELECT count(*) FROM logmov WHERE nro_doc = %s AND tip_mov = 'RET'", (doc,))[0] == 1
    _, member, _, _ = api.call("GET", "/api/v1/members/" + doc, "portal")
    assert member["status"] == "RETIRED"


def test_procedimiento_legacy_sigue_existiendo(legacy):
    assert legacy.one("SELECT count(*) FROM pg_proc WHERE proname = 'sp_registrar_retiro'")[0] == 1


def test_estado_de_migracion(api):
    status, body, _, _ = api.call("GET", "/api/v1/migration/status", "mobile")
    assert status == 200
    assert body["domains"]["affiliations"] in ("LEGACY", "DUAL", "MODERN")


def test_auditoria_completa_y_enmascarada(api, sample):
    api.call("GET", "/api/v1/members/" + sample["docs"]["active"], "portal")
    path = os.environ.get("AUDIT_LOG_PATH", "/logs/audit.log")
    with open(path, encoding="utf-8") as fh:
        lines = [line for line in fh.read().splitlines() if line.strip()][-200:]
    entries = [json.loads(line) for line in lines]
    assert entries and all(all(f in e for f in AUDIT_FIELDS) for e in entries)
    assert {e["consumer"] for e in entries} & {"portal", "subsidios", "mobile"}
    assert not any(doc in line for doc in sample["docs"].values() for line in lines)
