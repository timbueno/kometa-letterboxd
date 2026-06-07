#!/usr/bin/env bash
set -Eeuo pipefail

source_path="${BASH_SOURCE[0]}"
while [[ -h "$source_path" ]]; do
  source_dir="$(cd -P "$(dirname "$source_path")" >/dev/null 2>&1 && pwd)"
  source_path="$(readlink "$source_path")"
  if [[ "$source_path" != /* ]]; then
    source_path="$source_dir/$source_path"
  fi
done

project_dir="$(cd -P "$(dirname "$source_path")" >/dev/null 2>&1 && pwd)"
command_path="$project_dir/.venv/bin/kometa-letterboxd"
config_path="${KOMETA_LETTERBOXD_CONFIG:-$project_dir/config.yml}"
log_dir="${KOMETA_LETTERBOXD_LOG_DIR:-$project_dir/logs}"
log_file="${KOMETA_LETTERBOXD_LOG_FILE:-$log_dir/kometa-letterboxd.log}"
lock_file="${KOMETA_LETTERBOXD_LOCK_FILE:-$project_dir/.kometa-letterboxd.lock}"
lock_dir="$lock_file.d"

run_job() {
  cd "$project_dir"

  if [[ ! -x "$command_path" ]]; then
    echo "Error: executable not found at $command_path"
    return 127
  fi

  if [[ ! -f "$config_path" ]]; then
    echo "Error: config file not found at $config_path"
    return 2
  fi

  args=(--config "$config_path")
  if [[ -n "${KOMETA_LETTERBOXD_DATA:-}" ]]; then
    args+=(--data "$KOMETA_LETTERBOXD_DATA")
  fi

  echo "[$(date '+%Y-%m-%d %H:%M:%S %z')] Starting kometa-letterboxd"
  "$command_path" "${args[@]}"
  echo "[$(date '+%Y-%m-%d %H:%M:%S %z')] Finished kometa-letterboxd"
}

run_with_lock() {
  if command -v flock >/dev/null 2>&1; then
    (
      flock -n 9 || {
        echo "[$(date '+%Y-%m-%d %H:%M:%S %z')] Already running; exiting."
        exit 0
      }
      run_job
    ) 9>"$lock_file"
  else
    if ! mkdir "$lock_dir" 2>/dev/null; then
      echo "[$(date '+%Y-%m-%d %H:%M:%S %z')] Already running; exiting."
      exit 0
    fi
    trap 'rmdir "$lock_dir"' EXIT
    run_job
  fi
}

mkdir -p "$log_dir"
run_with_lock >>"$log_file" 2>&1
