#!/usr/bin/env bash
set -euo pipefail

# Cron-friendly wrapper around the verified staging backup. Recovery points
# live on Austin's separate cold-storage RAID, never in the application tree.
repo_dir="${STAGING_REPO_DIR:-/home/defibeats/shift6-staging}"
environment_file="${STAGING_ENV_FILE:-${repo_dir}/.env.staging}"
backup_root="${STAGING_BACKUP_ROOT:-/mnt/cold/backups/shift6-staging}"

if [[ "${repo_dir}" != "/home/defibeats/shift6-staging" ]]; then
  echo "refusing unexpected staging repository: ${repo_dir}" >&2
  exit 2
fi
if [[ "${backup_root}" != "/mnt/cold/backups/shift6-staging" ]]; then
  echo "refusing unexpected staging backup root: ${backup_root}" >&2
  exit 2
fi
if [[ ! -f "${environment_file}" ]]; then
  echo "staging environment file not found: ${environment_file}" >&2
  exit 2
fi

timestamp="$(date -u +%Y-%m-%dT%H%M%SZ)"
destination="${backup_root}/${timestamp}"
mkdir -p -- "${backup_root}"

STAGING_ENV_FILE="${environment_file}" \
  bash "${repo_dir}/ops/backup-staging.sh" \
  --destination "${destination}"

echo "nightly staging recovery point complete: ${destination}"
