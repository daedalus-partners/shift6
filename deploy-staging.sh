#!/usr/bin/env bash

set -Eeuo pipefail

readonly PROJECT_NAME="shift6-staging"
readonly EXPECTED_BRANCH="codex/phase1-staging"
readonly EXPECTED_ORIGIN_SSH="git@github.com:daedalus-partners/shift6.git"
readonly EXPECTED_ORIGIN_HTTPS="https://github.com/daedalus-partners/shift6.git"
readonly PRODUCTION_DIRECTORY="/var/www/shift6"

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ENV_FILE="${STAGING_ENV_FILE:-${ROOT_DIR}/.env.staging}"
if [[ "${ENV_FILE}" != /* ]]; then
  ENV_FILE="${ROOT_DIR}/${ENV_FILE}"
fi

die() {
  printf 'staging deploy refused: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

env_value() {
  local key="$1"
  awk -v wanted="${key}" '
    index($0, wanted "=") == 1 { value = substr($0, length(wanted) + 2) }
    END { sub(/\r$/, "", value); print value }
  ' "${ENV_FILE}"
}

validate_staging_environment() {
  [[ -f "${ENV_FILE}" ]] || die "missing ${ENV_FILE}; create it from .env.example"
  [[ "$(env_value APP_ENV)" == "staging" ]] || die "APP_ENV must equal staging"
  [[ "$(env_value AUTH_MODE)" == "cloudflare_access" ]] || die "AUTH_MODE must equal cloudflare_access"
  [[ "$(env_value CORS_ALLOW_ORIGINS)" == "https://shift6-staging.dwings.app" ]] || \
    die "CORS_ALLOW_ORIGINS must equal https://shift6-staging.dwings.app"
  [[ "$(env_value UI_BASE_URL)" == "https://shift6-staging.dwings.app" ]] || \
    die "UI_BASE_URL must equal https://shift6-staging.dwings.app"
  [[ "$(env_value API_BASE_URL)" == "https://shift6-staging.dwings.app" ]] || \
    die "API_BASE_URL must equal https://shift6-staging.dwings.app"
  [[ "$(env_value POSTGRES_DB)" == "shift6_staging" ]] || die "POSTGRES_DB must equal shift6_staging"

  local database_url password
  database_url="$(env_value DATABASE_URL)"
  [[ "${database_url}" == postgresql+psycopg://*@postgres:5432/shift6_staging ]] || \
    die "DATABASE_URL must target the staging postgres service and shift6_staging database"
  password="$(env_value POSTGRES_PASSWORD)"
  [[ -n "${password}" && "${password}" != "replace-me" ]] || die "set a unique staging POSTGRES_PASSWORD"

  [[ -n "$(env_value CF_ACCESS_TEAM_DOMAIN)" ]] || die "CF_ACCESS_TEAM_DOMAIN is required"
  [[ -n "$(env_value CF_ACCESS_AUDIENCE)" ]] || die "CF_ACCESS_AUDIENCE is required"

  # Phase 2 integrations must not write from staging.
  [[ -z "$(env_value SMTP_URL)" ]] || die "SMTP_URL must remain blank in staging"
  [[ -z "$(env_value GOOGLE_SCRIPT_URL)" ]] || die "GOOGLE_SCRIPT_URL must remain blank in staging"
  [[ -z "$(env_value GOOGLE_SERVICE_ACCOUNT_JSON)" ]] || \
    die "GOOGLE_SERVICE_ACCOUNT_JSON must remain blank in staging"
  [[ -z "$(env_value GOOGLE_SHEETS_ID)" ]] || die "GOOGLE_SHEETS_ID must remain blank in staging"
}

require_command docker
require_command git
require_command curl

[[ "${ROOT_DIR}" != "${PRODUCTION_DIRECTORY}" ]] || \
  die "this script may not run from the production checkout"
[[ -d "${ROOT_DIR}/.git" ]] || die "${ROOT_DIR} is not a Git checkout"

origin_url="$(git -C "${ROOT_DIR}" remote get-url origin)"
[[ "${origin_url}" == "${EXPECTED_ORIGIN_SSH}" || "${origin_url}" == "${EXPECTED_ORIGIN_HTTPS}" ]] || \
  die "unexpected Git origin: ${origin_url}"
current_branch="$(git -C "${ROOT_DIR}" branch --show-current)"
[[ "${current_branch}" == "${EXPECTED_BRANCH}" ]] || \
  die "checkout ${EXPECTED_BRANCH}; current branch is ${current_branch:-detached}"
[[ -z "$(git -C "${ROOT_DIR}" status --porcelain)" ]] || die "Git checkout has uncommitted or untracked files"

validate_staging_environment

compose=(
  docker compose
  --project-name "${PROJECT_NAME}"
  --env-file "${ENV_FILE}"
  -f "${ROOT_DIR}/docker-compose.yml"
  -f "${ROOT_DIR}/docker-compose.staging.yml"
)

git -C "${ROOT_DIR}" fetch --prune origin "${EXPECTED_BRANCH}"
git -C "${ROOT_DIR}" merge --ff-only "origin/${EXPECTED_BRANCH}"

# Revalidate after pulling because deployment files may have changed.
validate_staging_environment
"${compose[@]}" config --quiet
"${compose[@]}" up -d --build --remove-orphans

backend_port="$(env_value STAGING_BACKEND_PORT)"
backend_port="${backend_port:-8011}"
[[ "${backend_port}" =~ ^[0-9]+$ ]] || die "STAGING_BACKEND_PORT must be numeric"

healthy=0
for _ in {1..30}; do
  if curl --fail --silent --show-error --max-time 3 \
    "http://127.0.0.1:${backend_port}/health" >/dev/null; then
    healthy=1
    break
  fi
  sleep 2
done
[[ "${healthy}" -eq 1 ]] || die "backend health check failed on 127.0.0.1:${backend_port}"

for volume in pgdata uploads evidence; do
  docker volume inspect "${PROJECT_NAME}_${volume}" >/dev/null 2>&1 || \
    die "expected isolated volume is missing: ${PROJECT_NAME}_${volume}"
done

printf 'staging deployed successfully\n'
printf 'project=%s\n' "${PROJECT_NAME}"
printf 'commit=%s\n' "$(git -C "${ROOT_DIR}" rev-parse HEAD)"
printf 'health=http://127.0.0.1:%s/health\n' "${backend_port}"
