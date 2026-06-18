#!/usr/bin/env bash
# 在有 Docker + 外网的机器上运行一次，导出基础镜像供内网服务器 offline load
# Usage: bash save-base-images.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
mkdir -p images

MIRROR="docker.m.daocloud.io"
pull() { docker pull "$1"; }

echo "Pulling base images (needs internet once)..."
pull "${MIRROR}/library/python:3.11-slim"
pull "${MIRROR}/library/node:20-alpine"
pull "${MIRROR}/library/nginx:alpine"
pull "${MIRROR}/chromadb/chroma:latest"

docker tag "${MIRROR}/chromadb/chroma:latest" aiagnet-chromadb:latest
docker tag "${MIRROR}/library/nginx:alpine" aiagnet-nginx:latest

echo "Saving to images/*.tar ..."
docker save -o images/base-python-3.11-slim.tar "${MIRROR}/library/python:3.11-slim"
docker save -o images/base-node-20-alpine.tar "${MIRROR}/library/node:20-alpine"
docker save -o images/base-nginx-alpine.tar "${MIRROR}/library/nginx:alpine"
docker save -o images/base-chromadb.tar aiagnet-chromadb:latest
docker save -o images/base-nginx-tag.tar aiagnet-nginx:latest

echo ""
echo "Done. Copy images/ folder to air-gapped server together with this deploy package."
ls -lh images/
