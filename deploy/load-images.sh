#!/bin/bash
# =============================================================================
# 离线部署：加载 Docker 镜像（在目标离线机器上运行）
# 兼容 crane 生成的 .tar 和 gzip 压缩的 .tar.gz
# =============================================================================
set -e

IMAGES_DIR=${1:-./images}

if [ ! -d "$IMAGES_DIR" ]; then
    echo "错误：目录 $IMAGES_DIR 不存在"
    exit 1
fi

echo ">>> 从 $IMAGES_DIR/ 加载 Docker 镜像..."

# 加载 .tar 文件（crane 默认格式）
for f in "$IMAGES_DIR"/*.tar; do
    [ -f "$f" ] || continue
    echo "    加载: $f"
    docker load -i "$f"
done

# 加载 .tar.gz 文件（gzip 压缩格式）
for f in "$IMAGES_DIR"/*.tar.gz; do
    [ -f "$f" ] || continue
    echo "    加载: $f"
    docker load < "$f"
done

echo ""
echo ">>> 已加载镜像列表："
docker images
echo ""
echo ">>> 接下来构建应用镜像并启动："
echo "    cp .env.example .env   # 填写 OPENCODE_IMAGE 和 LLM Key"
echo "    docker compose build"
echo "    docker compose up -d"
