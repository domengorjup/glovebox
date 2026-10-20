#!/bin/sh
# Pick defaults from GLOVEBOX_MODE, then start the app.
# standalone (default): port 8080. addon: HA ingress port 8099, data in /data.
set -eu

case "${GLOVEBOX_MODE:-standalone}" in
  addon)
    export GLOVEBOX_PORT="${GLOVEBOX_PORT:-8099}"
    export DATA_DIR="${DATA_DIR:-/data}"
    ;;
  standalone)
    export GLOVEBOX_PORT="${GLOVEBOX_PORT:-8080}"
    export DATA_DIR="${DATA_DIR:-/data}"
    ;;
  *)
    echo "Unknown GLOVEBOX_MODE: ${GLOVEBOX_MODE}" >&2
    exit 1
    ;;
esac
export GLOVEBOX_HOST="${GLOVEBOX_HOST:-0.0.0.0}"

exec glovebox "$@"
