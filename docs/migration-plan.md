# Plan de migración por dominio

Migración incremental (patrón *strangler fig*): ningún dominio pasa de LEGACY a MODERN de golpe.

- **LEGACY:** las aplicaciones usan la base y el procedimiento heredados.
- **DUAL:** el gateway atiende lecturas y escrituras sobre la base legacy, y el camino viejo sigue disponible para volver atrás en segundos.
- **MODERN:** el dominio tiene su propio almacenamiento y el legacy solo recibe una réplica para quien aún lo lea.

| Dominio | Estado | Criterio para avanzar | Rollback |
|---|---|---|---|
| Afiliaciones | DUAL | 7 días sin diferencias entre gateway y legacy, 0 retiros perdidos o duplicados y 99 % de respuestas en menos de 500 ms | ./rollback.sh affiliations (Subsidios vuelve a sp_registrar_retiro en menos de 1 minuto) |
| Empresas | LEGACY | 100 % de las consultas del portal por /api/v1/companies durante 14 días y conteo de activos igual al reporte nocturno | ./rollback.sh companies y volver el portal a la consulta anterior |
| Aportes | LEGACY | Contrato de aportes publicado y 0 diferencias en 3 cierres mensuales comparados con el legacy | ./rollback.sh contributions y mantener la lectura directa de APORTES |

Estado actual que expone el gateway (`GET /api/v1/migration/status`): `affiliations: DUAL`, `companies: LEGACY`, `contributions: LEGACY`.

Siguiente dominio: Empresas

## Cómo se mide y cómo se vuelve atrás

- Cada petición queda en `logs/audit.log` (consumidor, ruta enmascarada, estado y latencia): de ahí salen los porcentajes y latencias de los criterios.
- La idempotencia se comprueba contando movimientos `RET` por `requestId` (tabla `gateway_retirement_requests`): debe haber exactamente uno.
- `./rollback.sh <dominio>` deja el dominio en LEGACY en menos de 3 minutos sin reiniciar aplicaciones; para avanzar se usa `./scripts/migration-state.sh <dominio> <estado>`.
