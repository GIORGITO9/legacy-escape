# Mapa de dependencias del legacy

Dependencias directas que tienen hoy las aplicaciones sobre la base legacy (fuente: `docs/procesos.md`,
el código de `services/` y el procedimiento `sp_registrar_retiro`). El portal y la app móvil no aparecen
porque no tocan la base: solo hablan HTTP con el gateway.

| Aplicación | Tabla | Operación | Criticidad |
|---|---|---|---|
| Educación | AFI_MAE | Lectura | Alta |
| Educación | EMPRESA | Lectura | Media |
| Subsidios | AFI_MAE | Escritura | Alta |
| Subsidios | LOGMOV | Escritura | Alta |
| Reportes nocturnos | AFI_MAE | Lectura | Media |
| Reportes nocturnos | LOGMOV | Lectura | Media |

Notas:

- Subsidios escribe a través de `sp_registrar_retiro` (actualiza estado y fecha de retiro en `AFI_MAE` e inserta el movimiento `RET` en `LOGMOV`). Tras la migración lo hace por el gateway; el camino directo queda solo para el rollback.
- Educación no se puede modificar: por eso el cambio de esquema debe coordinarse con su equipo (su consulta ya contempla `PERSON_MASTER`).
- `AFI_MAE` es la tabla más crítica: la usan las tres aplicaciones con acceso directo.
