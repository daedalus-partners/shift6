#!/usr/bin/env bash

set -Eeuo pipefail

readonly PROJECT_NAME="shift6-staging"
readonly CONFIRMATION_VALUE="shift6-staging"
readonly PRODUCTION_DIRECTORY="/var/www/shift6"

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
ENV_FILE="${STAGING_ENV_FILE:-${ROOT_DIR}/.env.staging}"
if [[ "${ENV_FILE}" != /* ]]; then
  ENV_FILE="${ROOT_DIR}/${ENV_FILE}"
fi
BACKUP_DIR=""
PRE_RESTORE_DESTINATION=""
CONFIRMATION=""
RESTORE_STARTED=0

die() {
  printf 'staging restore refused: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat >&2 <<'USAGE'
Usage: restore-staging.sh \
  --backup-dir /absolute/path/to/backup \
  --pre-restore-destination /absolute/path/to/new-safety-backup \
  --confirm-project shift6-staging
USAGE
}

env_value() {
  local key="$1"
  awk -v wanted="${key}" '
    index($0, wanted "=") == 1 { value = substr($0, length(wanted) + 2) }
    END { sub(/\r$/, "", value); print value }
  ' "${ENV_FILE}"
}

on_exit() {
  local status=$?
  if [[ "${status}" -ne 0 && "${RESTORE_STARTED}" -eq 1 ]]; then
    printf 'restore failed; attempting to restart the staging services\n' >&2
    "${compose[@]}" up -d postgres backend frontend >/dev/null 2>&1 || true
  fi
  exit "${status}"
}
trap on_exit EXIT

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backup-dir)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      BACKUP_DIR="$2"
      shift 2
      ;;
    --pre-restore-destination)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      PRE_RESTORE_DESTINATION="$2"
      shift 2
      ;;
    --confirm-project)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      CONFIRMATION="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage
      die "unknown argument: $1"
      ;;
  esac
done

[[ "${CONFIRMATION}" == "${CONFIRMATION_VALUE}" ]] || \
  die "pass --confirm-project ${CONFIRMATION_VALUE}"
[[ "${BACKUP_DIR}" == /* && -d "${BACKUP_DIR}" ]] || die "backup directory must exist and be absolute"
[[ "${PRE_RESTORE_DESTINATION}" == /* ]] || die "pre-restore destination must be absolute"
[[ ! -e "${PRE_RESTORE_DESTINATION}" ]] || die "pre-restore destination already exists"
[[ "${ROOT_DIR}" != "${PRODUCTION_DIRECTORY}" ]] || die "may not run from production checkout"
[[ -f "${ENV_FILE}" ]] || die "missing staging environment: ${ENV_FILE}"
[[ "$(env_value APP_ENV)" == "staging" ]] || die "APP_ENV must equal staging"
[[ "$(env_value POSTGRES_DB)" == "shift6_staging" ]] || die "POSTGRES_DB must equal shift6_staging"

for command_name in curl docker sha256sum tar; do
  command -v "${command_name}" >/dev/null 2>&1 || die "required command not found: ${command_name}"
done
for required_file in database.dump uploads.tar.gz evidence.tar.gz manifest.env SHA256SUMS; do
  [[ -f "${BACKUP_DIR}/${required_file}" ]] || die "backup is missing ${required_file}"
done
grep -Fqx 'FORMAT_VERSION=1' "${BACKUP_DIR}/manifest.env" || die "unsupported backup format"
grep -Fqx 'PROJECT_NAME=shift6-staging' "${BACKUP_DIR}/manifest.env" || die "backup belongs to another project"
grep -Fqx 'DATABASE_NAME=shift6_staging' "${BACKUP_DIR}/manifest.env" || die "backup targets another database"

verify_checksum() {
  local file="$1" expected actual matches
  matches="$(awk -v wanted="${file}" '$2 == wanted { count++; hash=$1 } END { if (count == 1) print hash }' \
    "${BACKUP_DIR}/SHA256SUMS")"
  [[ -n "${matches}" ]] || die "missing or duplicate checksum for ${file}"
  expected="${matches}"
  actual="$(sha256sum "${BACKUP_DIR}/${file}" | awk '{print $1}')"
  [[ "${actual}" == "${expected}" ]] || die "checksum mismatch for ${file}"
}
for backup_file in database.dump uploads.tar.gz evidence.tar.gz manifest.env; do
  verify_checksum "${backup_file}"
done

validate_archive() {
  local archive="$1" member
  while IFS= read -r member; do
    case "${member}" in
      /*|..|../*|*/../*|*/..)
        die "unsafe path in ${archive}: ${member}"
        ;;
    esac
  done < <(tar -tzf "${BACKUP_DIR}/${archive}")
  if tar -tvzf "${BACKUP_DIR}/${archive}" | awk 'substr($1, 1, 1) ~ /^[lh]$/ { found=1 } END { exit !found }'; then
    die "links are not permitted in ${archive}"
  fi
}
validate_archive uploads.tar.gz
validate_archive evidence.tar.gz

compose=(
  docker compose
  --project-name "${PROJECT_NAME}"
  --env-file "${ENV_FILE}"
  -f "${ROOT_DIR}/docker-compose.yml"
  -f "${ROOT_DIR}/docker-compose.staging.yml"
)
"${compose[@]}" config --quiet
[[ -n "$("${compose[@]}" ps --status running --quiet postgres)" ]] || die "staging postgres is not running"
"${compose[@]}" exec -T postgres pg_restore --list \
  < "${BACKUP_DIR}/database.dump" >/dev/null

# Preserve the current staging state before any destructive operation.
STAGING_ENV_FILE="${ENV_FILE}" bash "${ROOT_DIR}/ops/backup-staging.sh" \
  --destination "${PRE_RESTORE_DESTINATION}"

RESTORE_STARTED=1
"${compose[@]}" stop frontend backend

"${compose[@]}" exec -T postgres sh -eu -c '
  test "$POSTGRES_DB" = shift6_staging
  dropdb --if-exists -U "$POSTGRES_USER" "$POSTGRES_DB"
  createdb -U "$POSTGRES_USER" "$POSTGRES_DB"
'
"${compose[@]}" exec -T postgres sh -eu -c '
  test "$POSTGRES_DB" = shift6_staging
  pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    --exit-on-error --no-owner --no-privileges
' < "${BACKUP_DIR}/database.dump"

restore_archive() {
  local target="$1" archive="$2"
  [[ "${target}" == "/data/uploads" || "${target}" == "/data/evidence" ]] || \
    die "refusing unexpected volume target: ${target}"
  "${compose[@]}" run --rm -T --no-deps --entrypoint sh backend -eu -c '
    target="$1"
    case "$target" in
      /data/uploads|/data/evidence) ;;
      *) exit 70 ;;
    esac
    find "$target" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
    tar --no-same-owner --no-same-permissions -C "$target" -xzf -
  ' restore-volume "${target}" < "${BACKUP_DIR}/${archive}"
}
restore_archive /data/uploads uploads.tar.gz
restore_archive /data/evidence evidence.tar.gz

"${compose[@]}" up -d postgres backend frontend
backend_port="$(env_value STAGING_BACKEND_PORT)"
backend_port="${backend_port:-8011}"
healthy=0
for _ in {1..30}; do
  if curl --fail --silent --show-error --max-time 3 \
    "http://127.0.0.1:${backend_port}/health" >/dev/null; then
    healthy=1
    break
  fi
  sleep 2
done
[[ "${healthy}" -eq 1 ]] || die "restored backend did not become healthy"

RESTORE_STARTED=0
trap - EXIT
printf 'staging restore completed from %s\n' "${BACKUP_DIR}"
printf 'pre-restore safety backup: %s\n' "${PRE_RESTORE_DESTINATION}"
