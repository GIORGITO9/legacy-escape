# Legacy Escape — Torrado y Ordoñez

## Descripción

Capa de transición para modernizar el sistema legacy de una Caja de Compensación Familiar sin apagarlo. Construimos un gateway REST con un adapter y un modelo canónico para que el portal de servicios, Subsidios y la nueva app móvil consulten afiliados, beneficiarios y empresas y registren retiros sin conocer tablas, columnas ni códigos legacy, mientras Educación sigue leyendo la base como siempre. El dominio Afiliaciones queda en estado DUAL con rollback ejecutable.

## Integrantes

- Manuel Alejandro Torrado Vergel
- Giorgi Julian Ordoñez Garcia

## Requisitos

- Docker Engine 24 o superior con Docker Compose v2 (`docker compose`).
- Linux, macOS o Windows con Docker Desktop (los scripts se ejecutan con `bash`).
- Python 3.8+ solo para correr `./validator` en la máquina anfitriona.
- Puertos libres: 8082 (gateway), 8090, 8091 y 8092.

## Instalación y ejecución

Desde una copia limpia del repositorio:

```bash
cp .env.example .env          # y cambiar los tokens y la clave por valores propios
mkdir -p logs
docker compose up -d --build  # levanta legacy-db, gateway, portal, subsidios y educación
docker compose ps
curl http://localhost:8082/health
./validator check
```

Para devolver Afiliaciones al camino legacy (rollback, termina en segundos con código 0):

```bash
./rollback.sh affiliations
```

Para volver a avanzar el dominio: `./scripts/migration-state.sh affiliations DUAL`. Para reiniciar todo desde cero: `./reset.sh`.

## Configuración

Todas las variables están en `.env.example`; se copian a `.env` (que no se versiona) y se cambian los valores secretos.

| Variable | Para qué sirve | Valor de ejemplo |
|---|---|---|
| `POSTGRES_DB` | Nombre de la base legacy | `legacy` |
| `POSTGRES_USER` | Usuario de la base legacy (lo usan legacy-db, el adapter del gateway, Educación y el camino legacy de Subsidios) | `legacy` |
| `POSTGRES_PASSWORD` | Clave de ese usuario | `cambiar-esta-clave` |
| `LEGACY_DB_HOST` | Host de la base dentro de la red de Docker | `legacy-db` |
| `LEGACY_DB_PORT` | Puerto de PostgreSQL | `5432` |
| `GATEWAY_URL` | URL del gateway que usan el portal y Subsidios | `http://gateway:8082` |
| `PORTAL_TOKEN` | Token Bearer del portal (lee y puede registrar retiros) | `cambiar-portal` |
| `SUBSIDIOS_TOKEN` | Token Bearer de Subsidios (registra retiros) | `cambiar-subsidios` |
| `MOBILE_TOKEN` | Token Bearer de la app móvil (solo lectura: un POST recibe 403) | `cambiar-mobile` |

## Arquitectura

```text
portal-client / subsidios-app / app móvil → gateway (API v1 + modelo canónico + adapter) → legacy-db ← educacion-app
```

- `legacy-db`: PostgreSQL con las tablas heredadas y el procedimiento de retiros.
- `gateway`: API REST en Python (puerto 8082) construida desde `src/`. Autentica con un token por consumidor, audita cada petición en `logs/audit.log` con el documento enmascarado, guarda el estado de migración y la cola de retiros en un volumen propio, y es el único servicio nuevo que habla con `legacy-db` mediante el adapter `src/adapter/legacy_repository.py`.
- `portal-client`: portal que solo habla HTTP con `GATEWAY_URL` (sin cambios).
- `subsidios-app`: registra los retiros por el gateway con `SUBSIDIOS_TOKEN`; si Afiliaciones está en LEGACY o el gateway no existe, usa el procedimiento legacy (rollback).
- `educacion-app`: lee la base directamente, sin cambios, y ve los retiros porque se escriben en el legacy.
- `tests`: pruebas automatizadas de contrato (perfil `test`).

El detalle está en [docs/architecture.md](docs/architecture.md).

## Uso

Todas las rutas (salvo `/health`) piden `Authorization: Bearer <token>`.

**Salud** — `GET /health` responde `{"status": "UP", "legacy": "UP"}` (o `"legacy": "DOWN"`):

```bash
curl http://localhost:8082/health
```

**Afiliado** — `GET /api/v1/members/{document}` responde `{"document": "1019282447", "fullName": "IVAN HERNANDEZ GARCIA", "status": "ACTIVE", "company": {"id": "2014", "name": "AGROPECUARIA SANTANDER SA"}}`:

```bash
curl -H "Authorization: Bearer $PORTAL_TOKEN" http://localhost:8082/api/v1/members/1019282447
```

**Beneficiarios** — `GET /api/v1/members/{document}/beneficiaries` responde `[{"document": "1112049023", "fullName": "CLAUDIA JOSE PARRA MOLINA", "relationship": "SPOUSE"}]`:

```bash
curl -H "Authorization: Bearer $MOBILE_TOKEN" http://localhost:8082/api/v1/members/1019282447/beneficiaries
```

**Empresa** — `GET /api/v1/companies/{id}` responde `{"id": "2014", "name": "AGROPECUARIA SANTANDER SA", "activeMembers": 17}`:

```bash
curl -H "Authorization: Bearer $PORTAL_TOKEN" http://localhost:8082/api/v1/companies/2014
```

**Retiro** — `POST /api/v1/members/{document}/retirements` responde `201`; el mismo `requestId` otra vez responde `200` sin duplicar; con el legacy caído responde `202` y se aplica una sola vez al recuperarse:

```bash
curl -X POST -H "Authorization: Bearer $SUBSIDIOS_TOKEN" -H "Content-Type: application/json" -d '{"requestId": "ret-0001", "date": "2026-10-05", "reason": "Retiro voluntario"}' http://localhost:8082/api/v1/members/1019282447/retirements
```

**Estado de migración** — `GET /api/v1/migration/status` responde `{"domains": {"affiliations": "DUAL", "companies": "LEGACY", "contributions": "LEGACY"}}`:

```bash
curl -H "Authorization: Bearer $PORTAL_TOKEN" http://localhost:8082/api/v1/migration/status
```

Subsidios sigue respondiendo igual: `POST http://localhost:8091/retiros` con `{"documento", "fecha", "motivo"}`.
Errores: `{"message", "error_id"}`; legacy caído: `503` con `"code": "LEGACY_UNAVAILABLE"` en menos de 3 segundos.

## Pruebas

La suite en `tests/` (pytest) prueba la API en funcionamiento: salud, autenticación (401 sin token o con token inválido), permisos de la app móvil (lee 200, escribe 403), formato canónico del afiliado sin columnas legacy, beneficiarios y parentescos, conteo de afiliados activos por empresa, errores 404 con `error_id`, retiro visible en la base legacy, idempotencia por `requestId` (un solo movimiento), existencia del procedimiento legacy, estado de migración y auditoría enmascarada. Crea sus propios datos de prueba y los borra al terminar. Se ejecuta con el entorno levantado:

```bash
docker compose --profile test run --rm tests
```

El reporte JUnit queda en `test-results/junit.xml`.

## Documentación

- [docs/architecture.md](docs/architecture.md): contexto, componentes, modelo canónico, cambio de esquema y alternativas descartadas.
- [docs/dependency-map.md](docs/dependency-map.md): quién lee y quién escribe cada tabla legacy.
- [docs/migration-plan.md](docs/migration-plan.md): estados por dominio, criterios y rollback.
- [openapi.yaml](openapi.yaml): contrato v1 en OpenAPI 3.
- [AI_USAGE.md](AI_USAGE.md): cómo usamos la inteligencia artificial.

## Qué resolvimos

- Portal, Subsidios y móvil consumen la API sin conocer el esquema: todo el SQL vive en el adapter.
- El cambio de esquema (`scripts/schema-change.sh`) no afecta la API: el adapter detecta `PERSON_MASTER` y sigue respondiendo idéntico sin reiniciar.
- Los retiros pasan por el gateway, quedan en el legacy (Educación los ve) y son idempotentes con una tabla de `requestId` escrita en la misma transacción, evitando el duplicado del incidente de 2021.
- Con la base caída las consultas responden 503 controlado en menos de 3 segundos y los retiros se aceptan con 202 en una cola persistente que se aplica una sola vez al recuperarse, evitando la pérdida del incidente de 2023.
- La auditoría enmascara los documentos (incidente de 2025) y `./rollback.sh affiliations` devuelve Subsidios al procedimiento legacy.

## Limitaciones y pendientes

- Los dominios Empresas y Aportes siguen en LEGACY; el estado MODERN (almacenamiento propio del dominio) no se implementó.
- Los tokens son estáticos por consumidor; falta rotación, expiración y un gestor de secretos.
- No hay métricas automáticas que comparen gateway contra legacy para decidir el paso de DUAL a MODERN; hoy se leen de la auditoría.
- Los reportes nocturnos y Educación siguen leyendo la base directamente.
