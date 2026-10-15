# Arquitectura

## Contexto

La Caja de Compensación opera sobre una base legacy (réplica de Informix/Genero) que se volvió el punto de integración de todo: Educación, Subsidios y los reportes nocturnos leen y escriben directamente sus tablas, así que renombrar una columna rompe varias aplicaciones (incidente de 2019). La política de arquitectura prohíbe que una aplicación nueva se conecte a la base, y la dirección no acepta una migración Big Bang. Necesitamos una capa de transición que permita migrar dominio por dominio, empezando por Afiliaciones, sin apagar el negocio.

## Componentes

- **legacy-db:** PostgreSQL con las tablas heredadas (`AFI_MAE`, `AFI_BEN`, `EMPRESA`, `APORTES`, `LOGMOV`) y el procedimiento de retiros. No se modifica su contrato.
- **gateway (src/app):** API REST v1 en el puerto 8082. Autentica con un token Bearer por consumidor, aplica permisos (móvil solo lee), escribe la auditoría en `logs/audit.log` con el documento enmascarado, expone el estado de migración y mantiene una cola de retiros en un volumen propio (SQLite) para tolerar la caída del legacy.
- **adapter (src/adapter/legacy_repository.py):** único código nuevo que conoce tablas, columnas, códigos y el procedimiento legacy; traduce al modelo canónico. Corre dentro del contenedor del gateway.
- **portal-client:** solo habla HTTP con `GATEWAY_URL`.
- **panel-web:** panel de demostración (puerto 8093) que consume el gateway por HTTP con `PORTAL_TOKEN` guardado en el servidor; permite buscar afiliados, registrar retiros y ver el estado del legacy, la migración y la auditoría en vivo.
- **subsidios-app:** registra los retiros por el gateway con `SUBSIDIOS_TOKEN`; si Afiliaciones está en LEGACY o el gateway está desactivado, usa el procedimiento directamente (camino de rollback).
- **mobile-app:** app móvil del evento 3 (puerto 8094), nuevo consumidor de solo lectura: consulta afiliados y beneficiarios con `MOBILE_TOKEN` y el gateway le responde 403 si intenta escribir.
- **educacion-app:** sigue leyendo la base sin cambios y ve los retiros porque se escriben en el legacy.
- **tests:** pruebas de contrato con pytest contra la API en funcionamiento (perfil `test`).

Flujo: `Portal / Panel / Subsidios / App móvil → Gateway API → Modelo canónico → Adapter → legacy-db ← Educación`.

## Modelo canónico

El contrato usa nombres de negocio en inglés y valores cerrados, independientes del esquema legacy:

- **Member:** `document`, `fullName` (nombres y apellidos unidos), `status` (`A`→`ACTIVE`, `R`→`RETIRED`, `S`→`SUSPENDED`) y `company` `{id, name}`.
- **Beneficiary:** `document`, `fullName`, `relationship` (`C`→`SPOUSE`, `H`→`CHILD`, `P`→`FATHER`, `M`→`MOTHER`).
- **Company:** `id`, `name`, `activeMembers` (afiliados con estado activo).
- **Retirement:** `requestId` (clave de idempotencia), `document`, `date`, `reason`, `state` (`APPLIED` o `PENDING`) y `movementId`.
- **Error:** `message` y `error_id` (y `code` = `LEGACY_UNAVAILABLE` cuando la base no responde), sin trazas ni SQL.

Las clases viven en `src/app/domain.py`; los códigos de una letra solo existen dentro del adapter.

## Cambio de esquema

El DBA renombra `AFI_MAE → PERSON_MASTER`, `NRO_DOC → DOCUMENT_NUMBER` y `EST_AFI → STATUS_CODE`. El adapter declara las dos variantes del maestro de afiliados y ejecuta cada consulta con la última que funcionó; si PostgreSQL responde tabla o columna inexistente, prueba la otra variante y la recuerda. Así el gateway sigue respondiendo idéntico antes y después de `scripts/schema-change.sh`, sin reiniciar ni redesplegar, y el portal y los contratos no cambian. Los retiros usan el procedimiento, que el DBA actualiza junto con el cambio, así que Educación y los reportes siguen viendo los mismos datos.

## Alternativas descartadas

- **Migración Big Bang a una base nueva:** descartada porque obliga a apagar el negocio y a migrar Educación, que no se puede modificar; un error no tendría vuelta atrás rápida.
- **Dar a cada aplicación nueva acceso directo a la base (o vistas SQL compartidas):** descartada porque viola la política de arquitectura y repite el acoplamiento que causó el incidente de 2019; cualquier cambio de esquema volvería a romper consumidores.
- **Replicar datos con CDC / doble escritura desde el inicio:** descartada para esta fase por complejidad y riesgo de inconsistencias; el estado DUAL con el legacy como única fuente de verdad es más simple y reversible.
- **Idempotencia solo en memoria del gateway:** descartada porque un reinicio duplicaría retiros (incidente de 2021); usamos una tabla de requestId escrita en la misma transacción que el retiro.
