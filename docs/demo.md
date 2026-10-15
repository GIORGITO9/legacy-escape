# Guía de demostración

Recorrido de 5 minutos para mostrar la solución completa (también sirve de guion para el pitch de 60 segundos).

## Preparación

```bash
./reset.sh
```

Abrir en el navegador:

- Panel web: http://localhost:8093
- App móvil: http://localhost:8094
- Educación (sin cambios): http://localhost:8090/afiliados/13149818
- Portal (sin cambios): http://localhost:8092/portal/afiliados/13149818

## 1. Consulta por API, sin conocer el esquema

En el panel, buscar `1019282447`: ficha, beneficiarios y empresa salen del gateway en el modelo canónico (`ACTIVE`, `SPOUSE`…). El portal muestra lo mismo usando solo `GATEWAY_URL`.

## 2. Retiro migrado e idempotente

En el panel, buscar `13149818` y pulsar **Registrar retiro**. Recargar Educación: ahora dice `RETIRADO`. Repetir el mismo retiro desde Subsidios no duplica el movimiento:

```bash
curl -X POST -H "Content-Type: application/json" -d '{"documento":"13149818","fecha":"2026-10-05","motivo":"Retiro voluntario"}' http://localhost:8091/retiros
```

## 3. Nuevo consumidor de solo lectura

En la app móvil, buscar `6039066119` y pulsar **Solicitar retiro**: el gateway responde 403.

## 4. Falla del legacy

```bash
docker compose stop legacy-db
```

El panel muestra el aviso rojo; las consultas responden 503 `LEGACY_UNAVAILABLE` en menos de medio segundo y un retiro queda en cola (202). Al volver la base se aplica una sola vez:

```bash
docker compose start legacy-db
```

## 5. Cambio de esquema

```bash
./scripts/schema-change.sh
```

Las consultas del panel y del portal responden idéntico.

## 6. Rollback

```bash
./rollback.sh affiliations
```

El panel muestra Afiliaciones en `LEGACY` y Subsidios vuelve a `sp_registrar_retiro`.

## 7. Pruebas

```bash
docker compose --profile test run --rm tests
```

Al terminar, `./reset.sh` deja todo como al inicio.
