#!/usr/bin/env bash
# Sync this directory to your Docker host over SSH, then build and restart there.
# Docker is only used on the remote machine — nothing runs on your Mac.
# If the final `ssh … docker compose` step fails (e.g. env path), you can still rely
# on rsync and run `docker compose up -d --build` yourself on the host console.
#
# By default the whole `config/` directory is NOT rsynced so a remote symlink
# (e.g. config → ~/docker-data/dsc-panel/config) is not replaced by a real folder.
# Your real settings live on the host in that target directory: settings.txt, .env,
# zone_names.json. The app never reads settings.txt.example from the repo at runtime.
#
# Usage:
#   ./push-image-to-host.sh              # exclude entire config/
#   ./push-image-to-host.sh --with-config   # sync config/ but still skip .env & settings.txt
#   WITH_CONFIG=1 ./push-image-to-host.sh   # same as --with-config
#
# Env: NEUTRAL_SERVER=user@host:path (default csmykay@neutral:~/dsc-panel)

set -euo pipefail
cd "$(dirname "$0")"

EXCLUDE_CONFIG=1
for arg in "$@"; do
  case "$arg" in
    --with-config)
      EXCLUDE_CONFIG=0
      ;;
    -h|--help)
      cat <<'EOF'
Sync dsc-panel to Docker host and run docker compose up -d --build.

  ./push-image-to-host.sh
      Default: rsync excludes the whole config/ directory (keeps remote symlink).

  ./push-image-to-host.sh --with-config
  WITH_CONFIG=1 ./push-image-to-host.sh
      Rsync config/ too, but still exclude config/.env and config/settings.txt.

  NEUTRAL_SERVER=user@host:path  optional override (default csmykay@neutral:~/dsc-panel)
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $arg (use --help)" >&2
      exit 1
      ;;
  esac
done

if [[ "${WITH_CONFIG:-0}" == "1" ]]; then
  EXCLUDE_CONFIG=0
fi

NEUTRAL="${NEUTRAL_SERVER:-csmykay@neutral:~/dsc-panel}"
SSH_TARGET="${NEUTRAL%%:*}"
REMOTE_PATH="${NEUTRAL#*:}"

RSYNC=(rsync -avz --delete
  --exclude 'node_modules'
  --exclude '.git'
  --exclude '__pycache__'
  --exclude '.venv'
)

if [[ "$EXCLUDE_CONFIG" -eq 1 ]]; then
  RSYNC+=(--exclude 'config')
  echo "Rsyncing to $NEUTRAL (excluding config/) ..."
else
  RSYNC+=(--exclude 'config/.env' --exclude 'config/settings.txt')
  echo "Rsyncing to $NEUTRAL (including config/, excluding .env & settings.txt) ..."
fi

"${RSYNC[@]}" ./ "${NEUTRAL}/"

echo "Building and restarting on $SSH_TARGET ..."
# shellcheck disable=SC2029
ssh "$SSH_TARGET" "cd ${REMOTE_PATH} && docker compose up -d --build"

echo "Done."
