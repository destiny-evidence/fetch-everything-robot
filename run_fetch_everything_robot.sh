#!/usr/bin/env bash

set -euo pipefail

PORT=8001
TAG="latest"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)
      PORT="$2"
      shift 2
      ;;
    --tag)
      TAG="$2"
      shift 2
      ;;
    --help|-h)
      echo "Usage: $0 [--port PORT] [--tag TAG]"
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      echo "Usage: $0 [--port PORT] [--tag TAG]"
      exit 1
      ;;
  esac
done

docker run -p "$PORT":8001 --env-file .env fetch-everything-robot:"$TAG"
