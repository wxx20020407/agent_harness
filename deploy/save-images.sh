#!/bin/bash
# =============================================================================
# 离线部署辅助脚本：保存所有 Docker 镜像为 tar 文件
# 在有网络的机器上运行，生成的 tar 文件传输到内网机器后用 load-images.sh 加载
# =============================================================================
set -e

OUTPUT_DIR=${1:-./images}
mkdir -p "$OUTPUT_DIR"

# 读取 .env 中的 OPENCODE_IMAGE，没有则用默认值
OPENCODE_IMAGE=$(grep OPENCODE_IMAGE .env 2>/dev/null | cut -d= -f2 | tr -d '"' || echo "ghcr.io/sst/opencode:latest")

echo ">>> 保存镜像到 $OUTPUT_DIR/"
echo "    OPENCODE_IMAGE: $OPENCODE_IMAGE"

# 确保镜像已 pull
docker pull "$OPENCODE_IMAGE"
docker pull node:18-alpine
docker pull nginx:alpine

# 保存
echo ">>> 保存 opencode 镜像..."
docker save "$OPENCODE_IMAGE" | gzip > "$OUTPUT_DIR/opencode.tar.gz"

echo ">>> 保存 node:18-alpine..."
docker save node:18-alpine | gzip > "$OUTPUT_DIR/node18-alpine.tar.gz"

echo ">>> 保存 nginx:alpine..."
docker save nginx:alpine | gzip > "$OUTPUT_DIR/nginx-alpine.tar.gz"

echo ""
echo ">>> 完成！将 $OUTPUT_DIR/ 目录下的文件传输到目标机器，然后运行："
echo "    bash deploy/load-images.sh $OUTPUT_DIR"
ls -lh "$OUTPUT_DIR/"
