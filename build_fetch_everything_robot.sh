#!/usr/bin/env bash

set -euo pipefail

IMAGE_TAG="latest"
IGNORE_CACHE=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag=*|-t=*) IMAGE_TAG="${1#*=}" ;;
    --tag|-t) [[ -n "$2" && "$2" != -* ]] && IMAGE_TAG="$2" && shift ;;
    --no-cache) IGNORE_CACHE=true ;;
  esac
  shift
done

echo "Building Docker image fetch-everything-robot:$IMAGE_TAG"

DOCKER_BUILD_STRING="buildx build -t "fetch-everything-robot:${IMAGE_TAG}" ."
if $IGNORE_CACHE; then
  echo "Ignoring cache for this build."
  DOCKER_BUILD_STRING+=" --no-cache"
fi
docker ${DOCKER_BUILD_STRING}

echo "Build complete - fetch-everything-robot:$IMAGE_TAG"
