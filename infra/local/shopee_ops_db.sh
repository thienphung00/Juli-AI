#!/usr/bin/env bash
# The local Shopee Ops database (ADR-117 §6): migrate it, load exports into it.
#
#   infra/local/shopee_ops_db.sh migrate
#   infra/local/shopee_ops_db.sh load FOLDER "SHOP NAME"
#   infra/local/shopee_ops_db.sh psql
#
# Runs from the repo root with the repo's Python (PYTHON, default python). The URL is
# fixed to 127.0.0.1: this script never points at Supabase.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="${PYTHON:-python}"
export DATABASE_URL="postgresql://postgres@127.0.0.1:55433/juli_ops_local"
export PYTHONPATH="$ROOT/backend/src:$ROOT"
cd "$ROOT"

case "${1:-}" in
  migrate)
    "$PYTHON" agent-runtime/scripts/ci/ensure_postgrest_client_roles.py
    "$PYTHON" -m alembic upgrade head
    ;;
  load)
    folder="${2:?usage: load FOLDER \"SHOP NAME\"}"
    shop="${3:?usage: load FOLDER \"SHOP NAME\"}"
    "$PYTHON" scripts/load_shopee_exports.py "$folder" \
      --database-url "$DATABASE_URL" --bootstrap-local-shop "$shop"
    ;;
  psql)
    docker exec -it juli-shopee-ops-db psql -U postgres -d juli_ops_local
    ;;
  *)
    echo "usage: $0 migrate | load FOLDER \"SHOP NAME\" | psql" >&2
    exit 2
    ;;
esac
