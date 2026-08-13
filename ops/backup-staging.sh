#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

readonly PROJECT_NAME="shift6-staging"
readonly PRODUCTION_DIRECTORY="/var/www/shift6"

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
ENV_FILE="${STAGING_ENV_FILE:-${ROOT_DIR}/.env.staging}"
if [[ "${ENV_FILE}" != /* ]]; then
  ENV_FILE="${ROOT_DIR}/${ENV_FILE}"
fi
DESTINATION=""
WORK_DIR=""

die() {
  printf 'staging backup refused: %s\n' "$*" >&2
  exit 1
}

usage() {
  printf 'Usage: %s --destination /absolute/path/to/new-backup-directory\n' "$0" >&2
}

cleanup() {
  local status=$?
  if [[ -n "${WORK_DIR}" && -d "${WORK_DIR}" ]]; then
    rm -r -- "${WORK_DIR}"
  fi
  exit "${status}"
}
trap cleanup EXIT

while [[ $# -gt 0 ]]; do
  case "$1" in
    --destination)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      DESTINATION="$2"
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

[[ -n "${DESTINATION}" ]] || { usage; die "--destination is required"; }
[[ "${DESTINATION}" == /* ]] || die "destination must be an absolute path"
case "${DESTINATION}" in
  /|/var|/var/www|/var/www/shift6|/var/lib/docker|/var/lib/docker/*)
    die "unsafe destination: ${DESTINATION}"
    ;;
esac
[[ ! -e "${DESTINATION}" ]] || die "destination already exists: ${DESTINATION}"
[[ "${ROOT_DIR}" != "${PRODUCTION_DIRECTORY}" ]] || die "may not run from production checkout"
[[ -f "${ENV_FILE}" ]] || die "missing staging environment: ${ENV_FILE}"
command -v docker >/dev/null 2>&1 || die "docker is required"
command -v sha256sum >/dev/null 2>&1 || die "sha256sum is required"
command -v tar >/dev/null 2>&1 || die "tar is required"

compose=(
  docker compose
  --project-name "${PROJECT_NAME}"
  --env-file "${ENV_FILE}"
  -f "${ROOT_DIR}/docker-compose.yml"
  -f "${ROOT_DIR}/docker-compose.staging.yml"
)
"${compose[@]}" config --quiet

postgres_container="$("${compose[@]}" ps --status running --quiet postgres)"
[[ -n "${postgres_container}" ]] || die "staging postgres is not running"

parent_dir="$(dirname -- "${DESTINATION}")"
mkdir -p -- "${parent_dir}"
WORK_DIR="$(mktemp -d "${parent_dir}/.shift6-staging-backup.tmp.XXXXXX")"

"${compose[@]}" exec -T postgres sh -eu -c '
  test "$POSTGRES_DB" = shift6_staging
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    --format=custom --compress=9 --no-owner --no-privileges
' > "${WORK_DIR}/database.dump"

"${compose[@]}" run --rm -T --no-deps --entrypoint tar backend \
  -C /data/uploads -czf - . > "${WORK_DIR}/uploads.tar.gz"
"${compose[@]}" run --rm -T --no-deps --entrypoint tar backend \
  -C /data/evidence -czf - . > "${WORK_DIR}/evidence.tar.gz"

tar -tzf "${WORK_DIR}/uploads.tar.gz" >/dev/null
tar -tzf "${WORK_DIR}/evidence.tar.gz" >/dev/null

created_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
git_commit="unknown"
if [[ -d "${ROOT_DIR}/.git" ]]; then
  git_commit="$(git -C "${ROOT_DIR}" rev-parse HEAD)"
fi
{
  printf 'FORMAT_VERSION=1\n'
  printf 'PROJECT_NAME=%s\n' "${PROJECT_NAME}"
  printf 'DATABASE_NAME=shift6_staging\n'
  printf 'CREATED_AT=%s\n' "${created_at}"
  printf 'GIT_COMMIT=%s\n' "${git_commit}"
} > "${WORK_DIR}/manifest.env"

(
  cd "${WORK_DIR}"
  sha256sum database.dump uploads.tar.gz evidence.tar.gz manifest.env > SHA256SUMS
)

mv -T -- "${WORK_DIR}" "${DESTINATION}"
WORK_DIR=""
trap - EXIT
printf '%s\n' "${DESTINATION}"
