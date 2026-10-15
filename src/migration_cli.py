"""Cambia o consulta el estado de migración de un dominio (lo usa ./rollback.sh).

Uso: python migration_cli.py status
     python migration_cli.py set <dominio> <LEGACY|DUAL|MODERN>
"""

import json
import sys

from app.store import Store


def main(argv):
    store = Store()
    if len(argv) == 2 and argv[1] == "status":
        print(json.dumps({"domains": store.domain_states()}))
        return 0
    if len(argv) == 4 and argv[1] == "set":
        try:
            store.set_domain_state(argv[2], argv[3].upper())
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 2
        print(json.dumps({"domains": store.domain_states()}))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
