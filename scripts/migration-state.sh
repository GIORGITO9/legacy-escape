#!/usr/bin/env bash
# Consulta o avanza el estado de migración de un dominio.
#   ./scripts/migration-state.sh                       -> muestra todos los dominios
#   ./scripts/migration-state.sh affiliations MODERN   -> cambia el estado
set -euo pipefail
cd "$(dirname "$0")/.."

if [ "$#" -eq 0 ]; then
  docker compose exec -T gateway python migration_cli.py status
else
  docker compose exec -T gateway python migration_cli.py set "$1" "${2:?Falta el estado: LEGACY, DUAL o MODERN}"
fi
