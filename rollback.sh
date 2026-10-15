#!/usr/bin/env bash
# Rollback de un dominio a LEGACY.
#   ./rollback.sh affiliations
# Deja el dominio en LEGACY en el estado de migración del gateway. Con Afiliaciones en LEGACY,
# Subsidios vuelve a registrar los retiros directamente con el procedimiento legacy
# (lo consulta en cada retiro), así que no hace falta reiniciar ninguna aplicación.
set -euo pipefail
cd "$(dirname "$0")"

DOMAIN="${1:-}"
case "$DOMAIN" in
  affiliations|companies|contributions) ;;
  *)
    echo "Uso: ./rollback.sh <affiliations|companies|contributions>" >&2
    exit 2
    ;;
esac

[ -f .env ] || cp .env.example .env

if docker compose ps --status running --services 2>/dev/null | grep -qx gateway; then
  docker compose exec -T gateway python migration_cli.py set "$DOMAIN" LEGACY
else
  # El gateway está detenido: se cambia el estado en su volumen sin levantar dependencias.
  docker compose run --rm --no-deps -T gateway python migration_cli.py set "$DOMAIN" LEGACY
fi

echo "Rollback completado: $DOMAIN = LEGACY"
