#!/bin/bash

set -eu

# ============================================
# 启动 Pixel Canvas 后端容器
# ============================================

# ---- 镜像配置 ----
IMAGE="${IMAGE:-ccr.ccs.tencentyun.com/star/pixel}"
TAG="${TAG:-latest}"
CONTAINER_NAME="${CONTAINER_NAME:-pixel-backend}"
# `auto` (default) runs the one-off safety workflow only when Alembic reports
# a pending revision. Set true to force it or false for an emergency restart.
RUN_MIGRATIONS="${RUN_MIGRATIONS:-auto}"
RUN_AS_USER="$(id -u):$(id -g)"

# ---- 运行目录配置 ----
DEPLOY_DIR="$(pwd)"
ENV_FILE="${ENV_FILE:-${DEPLOY_DIR}/.env}"
SNAPSHOT_DIR="${SNAPSHOT_DIR:-${DEPLOY_DIR}/snapshots}"

if [ ! -f "${ENV_FILE}" ]; then
  echo "❌ env file not found: ${ENV_FILE}" >&2
  exit 1
fi

mkdir -p "${SNAPSHOT_DIR}"
SNAPSHOT_DIR="$(cd "${SNAPSHOT_DIR}" && pwd)"

echo "Pulling ${IMAGE}:${TAG}..."
docker pull "${IMAGE}:${TAG}"

case "${RUN_MIGRATIONS}" in
  true)
    SHOULD_MIGRATE=true
    ;;
  false)
    SHOULD_MIGRATE=false
    ;;
  auto)
    echo "Checking whether database migration is required..."
    set +e
    CURRENT_REVISION="$(docker run --rm \
      --network host \
      --user "${RUN_AS_USER}" \
      --env-file "${ENV_FILE}" \
      --env SNAPSHOT_DIRECTORY=/app/snapshots \
      --mount "type=bind,src=${SNAPSHOT_DIR},dst=/app/snapshots" \
      "${IMAGE}:${TAG}" alembic current 2>&1)"
    CURRENT_STATUS=$?
    set -e
    if [ "${CURRENT_STATUS}" -ne 0 ]; then
      echo "❌ could not inspect Alembic revision:" >&2
      echo "${CURRENT_REVISION}" >&2
      exit "${CURRENT_STATUS}"
    fi
    if printf '%s\n' "${CURRENT_REVISION}" | grep -Fq '(head)'; then
      SHOULD_MIGRATE=false
      echo "Database is already at the Alembic head; skipping migration safety workflow."
    else
      SHOULD_MIGRATE=true
      echo "Database revision is behind the image; migration safety workflow is required."
    fi
    ;;
  *)
    echo "❌ RUN_MIGRATIONS must be auto, true, or false" >&2
    exit 1
    ;;
esac

if [ "${SHOULD_MIGRATE}" = "true" ]; then
  echo "Checking legacy data before migration..."
  docker run --rm \
  --network host \
  --user "${RUN_AS_USER}" \
  --env-file "${ENV_FILE}" \
  --env SNAPSHOT_DIRECTORY=/app/snapshots \
  --mount "type=bind,src=${SNAPSHOT_DIR},dst=/app/snapshots" \
  "${IMAGE}:${TAG}" python scripts/pre_migration_audit.py

  # No process may write the canvas while migration and snapshot verification
  # establish the V2 recovery baseline.
  if docker container inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
    if [ "$(docker inspect -f '{{.State.Running}}' "${CONTAINER_NAME}")" = "true" ]; then
      echo "Stopping ${CONTAINER_NAME} for the migration..."
      docker stop "${CONTAINER_NAME}" >/dev/null
    fi
  fi

  echo "Running additive database migrations..."
  docker run --rm \
  --network host \
  --user "${RUN_AS_USER}" \
  --env-file "${ENV_FILE}" \
  --env SNAPSHOT_DIRECTORY=/app/snapshots \
  --mount "type=bind,src=${SNAPSHOT_DIR},dst=/app/snapshots" \
  "${IMAGE}:${TAG}" alembic upgrade head

  echo "Verifying legacy snapshot filename collisions..."
  docker run --rm \
  --network host \
  --user "${RUN_AS_USER}" \
  --env-file "${ENV_FILE}" \
  --env SNAPSHOT_DIRECTORY=/app/snapshots \
  --mount "type=bind,src=${SNAPSHOT_DIR},dst=/app/snapshots" \
  "${IMAGE}:${TAG}" python scripts/reconcile_legacy_snapshots.py --apply
fi

if docker container inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
  echo "Removing existing container ${CONTAINER_NAME}..."
  docker rm -f "${CONTAINER_NAME}" >/dev/null
fi

# ---- 运行容器 ----
docker run -d \
  --name "${CONTAINER_NAME}" \
  --restart unless-stopped \
  --init \
  --network host \
  --user "${RUN_AS_USER}" \
  --env-file "${ENV_FILE}" \
  --env SNAPSHOT_DIRECTORY=/app/snapshots \
  --mount "type=bind,src=${SNAPSHOT_DIR},dst=/app/snapshots" \
  "${IMAGE}:${TAG}"

echo "✅ ${CONTAINER_NAME} started"
echo "   snapshots: ${SNAPSHOT_DIR}"
