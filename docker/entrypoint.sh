#!/bin/sh
# Pick defaults from AUTOTRACKER_MODE, then start the app.
# standalone (default): port 8080. addon: HA ingress port 8099, data in /data.
set -eu

case "${AUTOTRACKER_MODE:-standalone}" in
  addon)
    export AUTOTRACKER_PORT="${AUTOTRACKER_PORT:-8099}"
    export DATA_DIR="${DATA_DIR:-/data}"
    ;;
  standalone)
    export AUTOTRACKER_PORT="${AUTOTRACKER_PORT:-8080}"
    export DATA_DIR="${DATA_DIR:-/data}"
    ;;
  *)
    echo "Unknown AUTOTRACKER_MODE: ${AUTOTRACKER_MODE}" >&2
    exit 1
    ;;
esac
export AUTOTRACKER_HOST="${AUTOTRACKER_HOST:-0.0.0.0}"

exec autotracker "$@"
