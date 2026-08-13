#!/usr/bin/env bash
set -e

if [[ "${RUN_MIGRATIONS:-true}" == "true" ]]; then
  echo "Running Alembic migrations..."
  alembic upgrade head
  echo "Alembic migrations complete."
else
  echo "Skipping Alembic migrations for this service."
fi

echo "Starting application..."
exec "$@"
